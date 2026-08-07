# P4 Stable Rollback

Production tags:

- `production-ppt-p4-object-animations-stable-20260724`
  - backend `fa85b313bbd1b55722f92fa7f86d7ac7589092f3`
  - frontend `80b8c9b0aa07826be29fd8f68b837cb0422a34ed`
- `rollback-ppt-p4-stable-backend-20260724` → `4111a46f566b4283856da993106256fc9758d730`
- `rollback-ppt-p4-stable-frontend-20260724` → `22ebfc967c0ae8512e45092d2e950e9bfe7ac37a`

P3-B fallback commits remain backend `0deaf853`, frontend `3bb8792`.

Current production sources are the stable worktrees. To roll back, restore the frontend systemd drop-in to the previous release worktree, restart `ai-box-frontend-3000.service`, then stop only the verified 8000 listener PID and start the selected backend rollback commit. Verify health, listener and editor smoke after each step.
