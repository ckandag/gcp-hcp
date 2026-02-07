---
name: Definition of Done
description: The definition of “done” (DoD) is a checklist of activities that the team can realistically commit to completing for each story/bug as a means of asserting that the work is completed.
tools: Read, Grep, Glob, Task
model: sonnet
---

# Definitions of Done

## Definition of Done: Story

In addition to meeting the requirements and any acceptance criteria from the Jira ticket, the developer must be able to check off the following activities for the story to be considered “done”:

1. Story satisfies all acceptance criteria
2. Test automation complete, where applicable:
   1. Unit test coverage at >= 85% and passing
   2. Integration tests added and passing
   3. e2e test added and passing
3. PR for code changes has been merged
4. AI-Assisted Development: Human-in-the-Loop Guidelines are followed (e.g. commit message conventions)  
5. PR for relevant architecture and design doc changes has been merged.  
6. Deployment to stage (once we have a stage platform\!)  
7. Story is demo-able for end of sprint

## Definition of Done: Spike

1. Spike findings are documented 
2. Decision is made and documented in the relevant design decision/architecture docs.
3. Resulting backlog items are created

## Definition of Done: Bugs

1. Test Added
    - Automated test included that verifies the fix
    - If not feasible, document why in the PR
2. Root Cause Documented
    - PR description explains what caused the bug
3. All Tests Pass
    – New and existing tests pass
    - No regressions introduced
4. Code Review Approved
    - At least one approval received
5. Ticket Closed
    - Link to merged PR added to bug ticket
   
