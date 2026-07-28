# Security Boundary

YagCode is a local tool. Its security boundary is the current operating-system user account plus the project directories explicitly approved by that user.

## Credentials

Provider keys are stored through the product credential flow backed by the OS keyring. The project does not provide a plaintext `.env` runtime fallback for submitted product behavior. Status, update, and clear flows never reveal the key value.

## Policy

Deterministic code governs:

- workspace and external path access;
- dangerous shell commands;
- network/provider egress;
- privacy preview and grant scope;
- destructive actions;
- dependency changes;
- push, release, deploy, and other publication paths.

Prompt text can explain the rules, but enforcement lives in repository code and is tested without a real LLM.

## Audit And Redaction

Audit output keeps structural evidence while avoiding raw credentials, private prompt content, Provider responses, and matched secret values. Secret scan reports detector IDs and locations only.

## Static Pages

The GitHub Pages site contains no task input, file upload, key field, Provider connection, sidecar client, shell, analytics, service worker, or dynamic browser runtime. It displays product positioning, screenshots, local demo commands, and links.
