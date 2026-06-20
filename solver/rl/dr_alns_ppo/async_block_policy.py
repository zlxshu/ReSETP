from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from .action_space import BLOCK_ACTION_NVECS
from .block_env import BLOCK_OBSERVATION_SIZE


class BlockActorCritic(nn.Module):
    def __init__(
        self,
        obs_dim: int = BLOCK_OBSERVATION_SIZE,
        action_nvec: tuple[int, ...] = tuple(BLOCK_ACTION_NVECS),
        hidden_size: int = 128,
    ) -> None:
        super().__init__()
        self.obs_dim = int(obs_dim)
        self.action_nvec = tuple(int(v) for v in action_nvec)
        self.hidden_size = int(hidden_size)
        self.backbone = nn.Sequential(
            nn.Linear(self.obs_dim, self.hidden_size),
            nn.Tanh(),
            nn.Linear(self.hidden_size, self.hidden_size),
            nn.Tanh(),
        )
        self.action_heads = nn.ModuleList([nn.Linear(self.hidden_size, n) for n in self.action_nvec])
        self.value_head = nn.Linear(self.hidden_size, 1)

    def forward(self, obs: torch.Tensor) -> tuple[list[torch.Tensor], torch.Tensor]:
        if obs.ndim == 1:
            obs = obs.unsqueeze(0)
        features = self.backbone(obs.float())
        logits = [head(features) for head in self.action_heads]
        values = self.value_head(features).squeeze(-1)
        return logits, values

    def distributions(self, obs: torch.Tensor) -> tuple[list[Categorical], torch.Tensor]:
        logits, values = self.forward(obs)
        return [Categorical(logits=logit) for logit in logits], values

    @torch.no_grad()
    def act(self, obs: np.ndarray | torch.Tensor, *, deterministic: bool = False) -> dict[str, Any]:
        obs_tensor = _obs_tensor(obs)
        dists, values = self.distributions(obs_tensor)
        actions: list[torch.Tensor] = []
        log_probs: list[torch.Tensor] = []
        entropies: list[torch.Tensor] = []
        for dist in dists:
            action = torch.argmax(dist.logits, dim=-1) if deterministic else dist.sample()
            actions.append(action)
            log_probs.append(dist.log_prob(action))
            entropies.append(dist.entropy())
        action_tensor = torch.stack(actions, dim=-1)
        return {
            "action": action_tensor.squeeze(0).cpu().numpy().astype(np.int64),
            "log_prob": torch.stack(log_probs, dim=-1).sum(dim=-1).squeeze(0).cpu().item(),
            "entropy": torch.stack(entropies, dim=-1).sum(dim=-1).squeeze(0).cpu().item(),
            "value": values.squeeze(0).cpu().item(),
        }

    def evaluate_actions(
        self,
        obs: torch.Tensor,
        actions: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        dists, values = self.distributions(obs)
        if actions.ndim == 1:
            actions = actions.unsqueeze(0)
        log_prob_parts = []
        entropy_parts = []
        for idx, dist in enumerate(dists):
            component = actions[:, idx].long()
            log_prob_parts.append(dist.log_prob(component))
            entropy_parts.append(dist.entropy())
        log_probs = torch.stack(log_prob_parts, dim=-1).sum(dim=-1)
        entropies = torch.stack(entropy_parts, dim=-1).sum(dim=-1)
        return log_probs, entropies, values


class AsyncBlockPolicy:
    def __init__(self, model: BlockActorCritic, metadata: dict[str, Any] | None = None) -> None:
        self.model = model
        self.model.eval()
        self.metadata = dict(metadata or {})

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        action = self.model.act(obs, deterministic=deterministic)["action"]
        return action, None


def make_block_actor_critic(seed: int = 1, hidden_size: int = 128) -> BlockActorCritic:
    torch.manual_seed(int(seed))
    model = BlockActorCritic(hidden_size=int(hidden_size))
    return model


def save_async_block_policy(
    path: str | Path,
    model: BlockActorCritic,
    *,
    metadata: dict[str, Any] | None = None,
) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "dr_alns_async_block_ppo.v1",
        "state_dict": {key: value.detach().cpu() for key, value in model.state_dict().items()},
        "obs_dim": int(model.obs_dim),
        "action_nvec": tuple(int(v) for v in model.action_nvec),
        "hidden_size": int(model.hidden_size),
        "metadata": dict(metadata or {}),
    }
    torch.save(payload, output)


def load_async_block_policy(path: str | Path, *, map_location: str | torch.device = "cpu") -> AsyncBlockPolicy:
    payload = torch.load(Path(path), map_location=map_location, weights_only=False)
    if not isinstance(payload, dict) or payload.get("format") != "dr_alns_async_block_ppo.v1":
        raise ValueError(f"not an async block PPO model: {path}")
    model = BlockActorCritic(
        obs_dim=int(payload["obs_dim"]),
        action_nvec=tuple(int(v) for v in payload["action_nvec"]),
        hidden_size=int(payload["hidden_size"]),
    )
    model.load_state_dict(payload["state_dict"])
    return AsyncBlockPolicy(model, metadata=dict(payload.get("metadata") or {}))


def is_async_block_model_path(path: str | Path) -> bool:
    return Path(path).suffix == ".pt"


def _obs_tensor(obs: np.ndarray | torch.Tensor) -> torch.Tensor:
    if isinstance(obs, torch.Tensor):
        tensor = obs.detach().float()
    else:
        tensor = torch.as_tensor(obs, dtype=torch.float32)
    if tensor.ndim == 1:
        tensor = tensor.unsqueeze(0)
    return tensor


__all__ = [
    "AsyncBlockPolicy",
    "BlockActorCritic",
    "is_async_block_model_path",
    "load_async_block_policy",
    "make_block_actor_critic",
    "save_async_block_policy",
]
