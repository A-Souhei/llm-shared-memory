# Memento

- Only call `memento_load` when the user explicitly asks for it.
- Before Claude Code compaction, ask the user: "Save a memento before compaction?" — if yes, distill the session (commands used, workflow steps, decisions, what to avoid) and call `memento_save`. Do not save LLM explanations or code outputs, only process.
