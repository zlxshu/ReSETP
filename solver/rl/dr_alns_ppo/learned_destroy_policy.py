from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from .action_space import BLOCK_Q_RATIOS, BLOCK_THRESHOLD_RATIOS, REPAIR_IDS
from .learned_destroy import LEARNED_CUSTOMER_FEATURE_DIM, LEARNED_GLOBAL_OBSERVATION_SIZE


LEARNED_DESTROY_ACTION_NVECS = (len(REPAIR_IDS), len(BLOCK_Q_RATIOS), len(BLOCK_THRESHOLD_RATIOS))


class LearnedDestroyActorCritic(nn.Module):
    def __init__(
        self,
        global_obs_dim: int = LEARNED_GLOBAL_OBSERVATION_SIZE,
        customer_feature_dim: int = LEARNED_CUSTOMER_FEATURE_DIM,
        hidden_size: int = 128,
    ) -> None:
        super().__init__()
        self.global_obs_dim = int(global_obs_dim)
        self.customer_feature_dim = int(customer_feature_dim)
        self.hidden_size = int(hidden_size)
        self.global_encoder = nn.Sequential(
            nn.Linear(self.global_obs_dim, self.hidden_size),
            nn.Tanh(),
            nn.Linear(self.hidden_size, self.hidden_size),
            nn.Tanh(),
        )
        self.customer_encoder = nn.Sequential(
            nn.Linear(self.customer_feature_dim, self.hidden_size),
            nn.Tanh(),
            nn.Linear(self.hidden_size, self.hidden_size),
            nn.Tanh(),
        )
        num_heads = 4 if self.hidden_size % 4 == 0 else 1
        self.set_attention = nn.MultiheadAttention(self.hidden_size, num_heads=num_heads, batch_first=True)
        self.set_attention_norm = nn.LayerNorm(self.hidden_size)
        self.global_context_norm = nn.LayerNorm(self.hidden_size)
        self.pointer_head = nn.Linear(self.hidden_size, 1)
        self.repair_head = nn.Linear(self.hidden_size, len(REPAIR_IDS))
        self.q_head = nn.Linear(self.hidden_size, len(BLOCK_Q_RATIOS))
        self.threshold_head = nn.Linear(self.hidden_size, len(BLOCK_THRESHOLD_RATIOS))
        self.value_head = nn.Linear(self.hidden_size, 1)

    def forward(
        self,
        global_obs: torch.Tensor,
        customer_features: torch.Tensor,
        customer_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        global_obs, customer_features, customer_mask = _prepare_inputs(global_obs, customer_features, customer_mask)
        global_state = self.global_encoder(global_obs.float())
        customer_state = self.customer_encoder(customer_features.float())
        attention_out, _weights = self.set_attention(
            customer_state,
            customer_state,
            customer_state,
            key_padding_mask=~customer_mask.bool(),
            need_weights=False,
        )
        customer_state = self.set_attention_norm(customer_state + attention_out)
        mask_float = customer_mask.float().unsqueeze(-1)
        set_context = (customer_state * mask_float).sum(dim=1) / mask_float.sum(dim=1).clamp_min(1.0)
        global_context = self.global_context_norm(global_state + set_context)
        pointer_logits = self.pointer_head(torch.tanh(customer_state + global_context.unsqueeze(1))).squeeze(-1)
        pointer_logits = pointer_logits.masked_fill(~customer_mask.bool(), -1e9)
        repair_logits = self.repair_head(global_context)
        q_logits = self.q_head(global_context)
        threshold_logits = self.threshold_head(global_context)
        values = self.value_head(global_context).squeeze(-1)
        return repair_logits, q_logits, threshold_logits, pointer_logits, values

    @torch.no_grad()
    def act(
        self,
        global_obs: np.ndarray | torch.Tensor,
        customer_features: np.ndarray | torch.Tensor,
        customer_mask: np.ndarray | torch.Tensor,
        *,
        deterministic: bool = False,
    ) -> dict[str, Any]:
        global_obs_t, customer_features_t, customer_mask_t = _prepare_inputs(global_obs, customer_features, customer_mask)
        repair_logits, q_logits, threshold_logits, pointer_logits, values = self.forward(global_obs_t, customer_features_t, customer_mask_t)
        repair_dist = Categorical(logits=repair_logits)
        q_dist = Categorical(logits=q_logits)
        threshold_dist = Categorical(logits=threshold_logits)
        if bool(deterministic):
            repair_idx = torch.argmax(repair_logits, dim=-1)
            q_idx = torch.argmax(q_logits, dim=-1)
            threshold_idx = torch.argmax(threshold_logits, dim=-1)
        else:
            repair_idx = repair_dist.sample()
            q_idx = q_dist.sample()
            threshold_idx = threshold_dist.sample()
        mask_count = int(customer_mask_t[0].sum().item())
        selected_count = _selected_count(mask_count, int(q_idx[0].item()))
        selected, pointer_log_prob, pointer_entropy = _select_without_replacement(
            pointer_logits[0],
            customer_mask_t[0],
            selected_count,
            deterministic=bool(deterministic),
        )
        log_prob = (
            repair_dist.log_prob(repair_idx)
            + q_dist.log_prob(q_idx)
            + threshold_dist.log_prob(threshold_idx)
            + pointer_log_prob.unsqueeze(0)
        )
        entropy = repair_dist.entropy() + q_dist.entropy() + threshold_dist.entropy() + pointer_entropy.unsqueeze(0)
        return {
            "repair_idx": int(repair_idx[0].item()),
            "q_idx": int(q_idx[0].item()),
            "threshold_idx": int(threshold_idx[0].item()),
            "selected_indices": selected.detach().cpu().numpy().astype(np.int64),
            "selected_count": int(selected_count),
            "log_prob": float(log_prob[0].detach().cpu().item()),
            "entropy": float(entropy[0].detach().cpu().item()),
            "value": float(values[0].detach().cpu().item()),
        }

    def evaluate_actions(
        self,
        global_obs: torch.Tensor,
        customer_features: torch.Tensor,
        customer_mask: torch.Tensor,
        repair_actions: torch.Tensor,
        q_actions: torch.Tensor,
        threshold_actions: torch.Tensor,
        selected_indices: torch.Tensor,
        selected_counts: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        repair_logits, q_logits, threshold_logits, pointer_logits, values = self.forward(global_obs, customer_features, customer_mask)
        repair_dist = Categorical(logits=repair_logits)
        q_dist = Categorical(logits=q_logits)
        threshold_dist = Categorical(logits=threshold_logits)
        log_probs = (
            repair_dist.log_prob(repair_actions.long())
            + q_dist.log_prob(q_actions.long())
            + threshold_dist.log_prob(threshold_actions.long())
        )
        entropies = repair_dist.entropy() + q_dist.entropy() + threshold_dist.entropy()
        pointer_log_probs, pointer_entropies = _evaluate_pointer_actions(
            pointer_logits,
            customer_mask.bool(),
            selected_indices.long(),
            selected_counts.long(),
        )
        return log_probs + pointer_log_probs, entropies + pointer_entropies, values


def make_learned_destroy_actor_critic(seed: int = 1, hidden_size: int = 128) -> LearnedDestroyActorCritic:
    torch.manual_seed(int(seed))
    return LearnedDestroyActorCritic(hidden_size=int(hidden_size))


def save_learned_destroy_policy(
    path: str | Path,
    model: LearnedDestroyActorCritic,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "dr_alns_learned_destroy_ppo.v2",
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "global_obs_dim": int(model.global_obs_dim),
        "customer_feature_dim": int(model.customer_feature_dim),
        "hidden_size": int(model.hidden_size),
        "architecture": "set_attention_pointer_v1",
        "metadata": dict(metadata or {}),
    }
    torch.save(payload, output)


def load_learned_destroy_policy(path: str | Path, *, map_location: str | torch.device = "cpu") -> LearnedDestroyActorCritic:
    payload = torch.load(Path(path), map_location=map_location, weights_only=False)
    if not isinstance(payload, dict) or payload.get("format") not in {"dr_alns_learned_destroy_ppo.v1", "dr_alns_learned_destroy_ppo.v2"}:
        raise ValueError(f"not a learned-destroy PPO model: {path}")
    model = LearnedDestroyActorCritic(
        global_obs_dim=int(payload["global_obs_dim"]),
        customer_feature_dim=int(payload["customer_feature_dim"]),
        hidden_size=int(payload["hidden_size"]),
    )
    model.load_state_dict(payload["state_dict"], strict=False)
    model.eval()
    return model


def _prepare_inputs(
    global_obs: np.ndarray | torch.Tensor,
    customer_features: np.ndarray | torch.Tensor,
    customer_mask: np.ndarray | torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    obs = torch.as_tensor(global_obs, dtype=torch.float32) if not isinstance(global_obs, torch.Tensor) else global_obs.float()
    features = (
        torch.as_tensor(customer_features, dtype=torch.float32)
        if not isinstance(customer_features, torch.Tensor)
        else customer_features.float()
    )
    mask = torch.as_tensor(customer_mask, dtype=torch.bool) if not isinstance(customer_mask, torch.Tensor) else customer_mask.bool()
    if obs.ndim == 1:
        obs = obs.unsqueeze(0)
    if features.ndim == 2:
        features = features.unsqueeze(0)
    if mask.ndim == 1:
        mask = mask.unsqueeze(0)
    if obs.shape[0] != features.shape[0] or obs.shape[0] != mask.shape[0]:
        raise ValueError("batch dimension mismatch for learned-destroy inputs")
    if features.shape[:2] != mask.shape:
        raise ValueError("customer feature and mask shapes are inconsistent")
    if not bool(mask.any(dim=-1).all()):
        mask = mask.clone()
        empty = ~mask.any(dim=-1)
        mask[empty, 0] = True
    return obs, features, mask


def _selected_count(mask_count: int, q_idx: int) -> int:
    if mask_count <= 0:
        return 0
    q_ratio = float(BLOCK_Q_RATIOS[int(q_idx)])
    return max(1, min(int(mask_count), int(math.ceil(q_ratio * float(mask_count)))))


def _select_without_replacement(
    pointer_logits: torch.Tensor,
    customer_mask: torch.Tensor,
    selected_count: int,
    *,
    deterministic: bool,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    if int(selected_count) <= 0:
        empty = torch.zeros((0,), dtype=torch.long, device=pointer_logits.device)
        zero = pointer_logits.new_tensor(0.0)
        return empty, zero, zero
    available = customer_mask.clone().bool()
    selected: list[torch.Tensor] = []
    log_probs: list[torch.Tensor] = []
    entropies: list[torch.Tensor] = []
    for _ in range(int(selected_count)):
        masked_logits = pointer_logits.masked_fill(~available, -1e9)
        dist = Categorical(logits=masked_logits)
        idx = torch.argmax(masked_logits, dim=-1) if deterministic else dist.sample()
        selected.append(idx)
        log_probs.append(dist.log_prob(idx))
        entropies.append(dist.entropy())
        available = available.clone()
        available[idx] = False
        if not bool(available.any()):
            break
    return torch.stack(selected), torch.stack(log_probs).sum(), torch.stack(entropies).sum()


def _evaluate_pointer_actions(
    pointer_logits: torch.Tensor,
    customer_mask: torch.Tensor,
    selected_indices: torch.Tensor,
    selected_counts: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    batch_size, _customer_count = pointer_logits.shape
    available = customer_mask.clone().bool()
    log_probs = pointer_logits.new_zeros((batch_size,))
    entropies = pointer_logits.new_zeros((batch_size,))
    max_steps = int(selected_indices.shape[1]) if selected_indices.ndim == 2 else 0
    for step in range(max_steps):
        active = selected_counts > step
        if not bool(active.any()):
            break
        masked_logits = pointer_logits.masked_fill(~available, -1e9)
        dist = Categorical(logits=masked_logits)
        idx = selected_indices[:, step].clamp(min=0, max=pointer_logits.shape[1] - 1)
        step_log_prob = dist.log_prob(idx)
        step_entropy = dist.entropy()
        log_probs = log_probs + torch.where(active, step_log_prob, torch.zeros_like(step_log_prob))
        entropies = entropies + torch.where(active, step_entropy, torch.zeros_like(step_entropy))
        row_indices = torch.arange(batch_size, device=pointer_logits.device)
        available = available.clone()
        available[row_indices[active], idx[active]] = False
        empty = ~available.any(dim=-1)
        if bool(empty.any()):
            available[empty, 0] = True
    return log_probs, entropies


__all__ = [
    "LEARNED_DESTROY_ACTION_NVECS",
    "LearnedDestroyActorCritic",
    "load_learned_destroy_policy",
    "make_learned_destroy_actor_critic",
    "save_learned_destroy_policy",
]
