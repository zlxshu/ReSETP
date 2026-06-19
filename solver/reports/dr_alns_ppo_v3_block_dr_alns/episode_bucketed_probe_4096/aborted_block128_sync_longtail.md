# Aborted block_size=128 episode-bucketed probe

The probe restored concurrent worker launch, but `block_size=128` was still too fine-grained. The first 4096-eval phase had no completed episode after roughly 12 minutes and was dominated by a single long-tail worker. Next probe uses `block_size=512` to reduce synchronization barriers.
