#!/usr/bin/env bash
# Injects project_id (git repo name) into biblion indexer tool calls.
input=$(cat)
tool=$(echo "$input" | jq -r '.tool_name')

if [[ "$tool" == mcp__biblion__indexer_search || "$tool" == mcp__biblion__indexer_ingest ]]; then
  repo_name=$(git -C "$(pwd)" rev-parse --show-toplevel 2>/dev/null | xargs basename 2>/dev/null)
  if [[ -n "$repo_name" ]]; then
    updated=$(echo "$input" | jq --arg pid "$repo_name" '.tool_input.project_id = $pid')
    echo "$updated" | jq '{hookSpecificOutput: {hookEventName: "PreToolUse", updatedInput: .tool_input}}'
    exit 0
  fi
fi
