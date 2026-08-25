# ULTRON Autonomous Development Rules

This repository is the ULTRON project.

## Autonomous execution

For this repository, operate autonomously for normal software-development tasks.

Do NOT repeatedly ask the user for confirmation before:
- reading project files
- editing source code
- creating tests
- running tests
- running linters
- running builds
- fixing test failures
- fixing compilation errors
- updating documentation
- creating commits
- continuing through the approved phase workflow

When a task/phase has already been explicitly approved by the user, continue through the entire implementation workflow without pausing for confirmation.

## Required workflow

Use:

GSD → PLAN
→ IMPLEMENT
→ TEST
→ FIX
→ REVIEW
→ FIX REVIEW FINDINGS
→ FULL REGRESSION
→ COMMIT
→ REPORT

Do not stop between these stages to ask for permission.

## Phase boundaries

A phase must not automatically start if the user has not approved that phase.

However, once the user explicitly says to implement/start the current approved phase, complete that phase autonomously.

Do not ask:
"Should I continue?"
"Should I run the tests?"
"Should I fix this?"
"Should I commit?"

Instead, perform the obvious next development action.

## Safe autonomous actions

You may automatically:
- inspect repository files
- edit project files
- create/update tests
- run pytest
- run frontend tests
- run builds
- run formatting/linting
- debug failures
- retry failed commands
- make minimal corrective changes
- run regression tests
- create Git commits
- generate reports
- update roadmap/task documentation

## Git rules

Before changing code:
- inspect git status
- inspect current branch
- inspect recent commit

After implementation:
- inspect diff
- run tests
- commit only intended project changes

Never commit:
- .env
- API keys
- OAuth tokens
- passwords
- device credentials
- local auth tokens
- databases
- .venv
- build caches
- temporary files
- secrets

Never force-push unless the user explicitly requests it.

## Security rules

Never weaken:
- Authentication
- Authorization
- ExecutionContext
- PermissionStore
- SafetyGate
- ConfirmationBroker
- ToolExecutor
- Verification
- Audit
- EmergencyStop

Never bypass security just to make tests pass.

## Testing rules

Always fix failures rather than deleting or weakening tests.

Run the smallest focused test first after a fix, then run the full regression suite.

Target:
0 failed tests.

Skipped live-provider tests are acceptable when credentials are intentionally unavailable.

## External side effects

Normal development actions may proceed autonomously.

For irreversible real-world side effects such as:
- sending real email
- sending real SMS
- purchases
- deleting user data
- production deployment
- publishing releases
- changing GitHub repository permissions

stop and ask the user before performing the side effect.

## Release rules

Do not publish a release or deploy production artifacts without explicit user approval.

Local build/test/package operations may be performed autonomously.

## Phase completion

When the current phase is complete:
- run the full regression suite
- verify git status
- commit the phase
- produce a concise completion report

Do NOT automatically start the next phase.

## Communication style

Do not repeatedly ask for confirmation for routine engineering work.

Only ask when:
1. requirements are genuinely ambiguous,
2. a destructive/irreversible external side effect is about to occur,
3. credentials or secrets are required,
4. the user must choose between materially different architectures.

Otherwise make the reasonable engineering decision and continue.