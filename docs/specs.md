# Project Description: Hierarchical Branching Chat on Open WebUI

## 1. Overview

Build a customized chat application based on **Open WebUI** that supports long-running, persistent conversations with **hierarchical side conversations**.

The core problem is that normal chat interfaces treat a conversation as one linear stream. During a long discussion, users often want to temporarily explore a question, assumption, implementation detail, or alternative direction without adding that exploration to the main conversation's future context.

The application should allow the user to create a **branch or side thread from any point in a conversation**, continue that discussion independently, create further nested branches from that side thread, and later return to any previous thread.

All threads and their relationships must be persisted.

The experience should feel similar to **Git branches applied to conversations**.

---

# 2. Core Concept

A conversation workspace consists of a tree of **threads**.

Example:

```text
Main conversation
│
├── Pricing discussion
│   │
│   ├── Enterprise pricing
│   │
│   └── Competitor analysis
│   │
│   └── continue Pricing discussion
│
├── Technical architecture
│   │
│   ├── Database design
│   └── Context management
│
└── continue Main conversation
```

Each thread is itself a normal ChatGPT-style conversation.

A child thread inherits context from its ancestors **up to the point where it was created**, but messages generated inside the child thread do not become part of the parent thread.

This isolation is the central requirement.

---

# 3. Primary User Scenario

The user is having a long-running discussion:

```text
Main:

User → A
Assistant → B
User → C
Assistant → D
User → E
Assistant → F
```

At message `D`, the user wants to investigate a related question without changing the direction of the main conversation.

They select:

> Start side thread

A new thread is created:

```text
Main
A → B → C → D → E → F

             │
             └── Side Thread
                 G → H → I → J
```

When interacting with the side thread, the model receives:

```text
A
B
C
D
G
H
I
J
```

It does **not** receive:

```text
E
F
```

because those happened on the parent after the branch point.

When the user returns to the Main thread, its context remains:

```text
A
B
C
D
E
F
```

The side discussion is not included.

---

# 4. Nested Branching

Side threads must support the exact same branching behavior.

Example:

```text
Main
│
├── Pricing
│   │
│   ├── Competitors
│   │   │
│   │   ├── Competitor A
│   │   └── Competitor B
│   │
│   └── Packaging
│
└── Architecture
```

There must be no predefined maximum nesting depth.

---

# 5. Thread Model

Introduce a first-class `Thread` or equivalent concept.

Conceptually:

```text
Thread
------
id
workspace_id
title
parent_thread_id
branch_from_message_id
created_at
updated_at
```

Each thread contains its own messages.

```text
Message
-------
id
thread_id
parent_message_id
role
content
created_at
```

Open WebUI's existing message branching structure should be preserved where possible.

The new Thread hierarchy exists **above the message tree**.

Conceptually:

```text
Workspace
│
├── Thread
│   ├── Message tree
│   │
│   ├── Child Thread
│   │   ├── Message tree
│   │   └── Child Thread
│   │
│   └── Child Thread
```

This means two kinds of branching may coexist:

1. **Message branching**
   - Alternative regenerated responses.
   - Existing Open WebUI behavior.

2. **Thread branching**
   - Separate persistent discussions.
   - New functionality introduced by this project.

Do not conflate the two.

---

# 6. Structural Context Inheritance

Prefer **structural inheritance** rather than duplicating the complete ancestor conversation when creating a side thread.

For example:

```text
Thread T1
A → B → C → D → E

Thread T2
parent_thread_id = T1
branch_from_message_id = C

F → G → H
```

The model context for `T2` should be constructed dynamically as:

```text
T1 from beginning → C
+
T2 messages F → G → H
```

If another branch is created:

```text
T3
parent_thread_id = T2
branch_from_message_id = G

I → J
```

Then T3's inherited context becomes:

```text
T1 → C
+
T2 → G
+
T3 messages
```

This preserves the real conversation structure instead of creating duplicated copies.

---

# 7. Context Isolation

This is a strict functional requirement.

Messages from descendants must never automatically enter an ancestor's context.

Example:

```text
Main
│
├── Pricing
│   └── Competitors
│
└── Architecture
```

While inside `Main`, the model must not automatically know about:

- Pricing
- Competitors
- Architecture

While inside `Pricing`, the model may inherit Main context up to its branch point, but must not automatically know about:

- later Main messages
- Architecture
- sibling threads

While inside `Competitors`, the model may inherit:

```text
Main → Pricing → Competitors
```

but not unrelated branches.

---

# 8. Branch Creation

The user must be able to create a side thread from any appropriate message.

Possible action menu:

```text
Copy
Regenerate
Start side thread
...
```

Selecting **Start side thread** creates a child thread attached to that exact message.

Optionally allow branching from:

- the complete message
- selected text inside a message

For the first implementation, branching from the complete message is sufficient.

---

# 9. Thread Naming

Each side thread should have a title.

Initially:

- automatically generate the title using the LLM

The user must also be able to rename it.

Example:

```text
Main
├── Pricing strategy
├── Technical architecture
└── Launch plan
```

Titles are organizational metadata only and should not change the model context.

---

# 10. Navigation

Add a persistent hierarchical thread navigator.

Example:

```text
Project Discussion

● Main

├── Pricing
│   ├── Enterprise
│   └── Competitors
│
├── Architecture
│   ├── Database
│   └── Context management
│
└── Launch
```

The currently active thread should be clearly indicated.

Clicking a thread should immediately switch the conversation pane to that thread.

The hierarchy should remain visible while navigating.

---

# 11. Thread Tree UX

The tree should support:

- expand/collapse
- arbitrary nesting
- active-thread indication
- renaming
- deleting or archiving a thread
- creating a branch
- displaying unread/new activity if relevant later

Optional future capabilities:

- drag-and-drop organization
- move thread under another parent
- duplicate thread
- merge insights back into parent
- pin important threads

Do not make these advanced features a requirement for the initial version.

---

# 12. Persistence

All of the following must survive:

- browser refresh
- logout/login
- application restart
- server restart
- multi-day or multi-month usage

Persist:

- threads
- messages
- branch relationships
- branch points
- thread titles
- timestamps
- active model/provider
- relevant conversation settings

The conversation tree itself is important user data and must never exist only in frontend state.

---

# 13. Long-Running Conversations

The system must support conversations that continue for weeks or months.

Persistence and model context should be treated as separate concerns.

```text
Persistent history
        │
        └── everything remains stored

LLM context
        │
        └── only the relevant subset is sent
```

The application should never delete historical messages merely because they no longer fit inside a model's context window.

---

# 14. Context Compaction

Reuse Open WebUI's existing long-context management where practical.

Eventually, context construction should support:

```text
Recent messages
+
summary of older messages
+
relevant inherited ancestor context
```

Example:

```text
Main thread summary
+
Main messages near branch point
+
Pricing thread summary
+
Recent Pricing messages
+
Current Competitor messages
```

The initial implementation may rely primarily on existing Open WebUI context behavior, provided branch isolation remains correct.

Context optimization can be improved later.

---

# 15. Thread Context Inspector

Provide a way to understand what information is being inherited by the current thread.

For example:

```text
Context

Inherited from:
Main → message 43
Pricing → message 12

Current thread:
Competitor analysis
```

A more advanced version may allow displaying:

```text
Main
  34 messages inherited

Pricing
  12 messages inherited

Current thread
  8 messages
```

This is useful because context inheritance otherwise becomes invisible and difficult to reason about.

It is optional for the first MVP, but the architecture should support it.

---

# 16. Bringing Information Back to Parent

Child threads must not automatically affect their parents.

However, a future capability should allow the user to explicitly bring findings back.

Possible actions:

```text
Summarize into parent
```

or:

```text
Send conclusion to parent
```

The system would generate a concise summary of the side thread and append it to the parent as a new message.

Example:

```text
Competitor investigation
        ↓

[Bring to Pricing]

        ↓

Pricing:

"Summary from Competitor investigation:
..."
```

This must always be explicit.

No automatic merging.

This is a post-MVP capability.

---

# 17. Open WebUI Integration Strategy

Use the latest appropriate Open WebUI codebase as the foundation rather than rebuilding standard chat infrastructure.

Retain as much existing functionality as practical, including:

- model/provider support
- OpenAI-compatible APIs
- Anthropic integration
- local models where supported
- message streaming
- persistence
- authentication
- chat history
- message rendering
- markdown
- attachments
- file support
- tools/function calls
- existing message branches
- chat search
- long-context handling
- chat settings

The project should primarily modify or extend:

```text
conversation/thread domain model

fork semantics

context reconstruction

thread navigation

branch creation UX

thread persistence
```

Avoid rewriting unrelated Open WebUI functionality.

---

# 18. Existing Fork Behavior

Open WebUI already supports creating a separate conversation from part of an existing conversation.

Do not simply expose this current behavior under a different name.

The goal is to change the conceptual model from:

```text
Chat
    ↓ duplicate
Independent Chat
```

to:

```text
Parent Thread
    │
    └── Child Thread
```

The parent-child relationship must remain persistent and queryable.

---

# 19. Workspace Concept

A workspace represents the overall subject or long-running discussion.

Example:

```text
Workspace:
Astorna Strategy
```

Inside:

```text
Main
├── Workshop
├── Pricing
├── Website
└── Outreach
```

For an initial implementation, an existing Open WebUI conversation may effectively act as the workspace root.

However, the architecture should avoid preventing a separate `Workspace` entity from being introduced later.

Potential future structure:

```text
Workspace
---------
id
title
created_at
updated_at

Thread
------
workspace_id
...
```

---

# 20. Main Thread

Every workspace must have exactly one root thread.

This can be presented to the user as:

```text
Main
```

The root thread has:

```text
parent_thread_id = NULL
branch_from_message_id = NULL
```

All other threads ultimately descend from it.

---

# 21. URL and Navigation State

Ideally, every thread should be directly addressable.

For example:

```text
/chat/<workspace-id>/thread/<thread-id>
```

This allows:

- browser history navigation
- bookmarks
- refresh without losing location
- opening multiple branches in separate browser tabs

Thread identity should never depend solely on temporary frontend state.

---

# 22. Search

Existing Open WebUI conversation search should be retained.

Eventually search results should indicate where a message lives:

```text
Astorna Strategy
→ Pricing
→ Competitors
→ "Anthropic pricing is..."
```

Search does not need to understand the full hierarchy for the initial MVP, but messages inside side threads must remain searchable.

---

# 23. Data Deletion

Deleting a child thread requires explicit handling.

If the thread has no descendants:

```text
Delete thread
```

If descendants exist, the UI should warn:

```text
This thread contains 4 nested threads.

Delete:
○ this thread and all descendants
○ cancel
```

Do not silently orphan descendants.

Re-parenting descendants can be implemented later.

---

# 24. Model Independence

The hierarchy and persistence system must not depend on a specific model vendor.

Users should remain able to use any provider supported by Open WebUI, including potentially:

- OpenAI
- Anthropic
- Gemini
- OpenRouter
- OpenAI-compatible APIs
- local models

A branch should also be able to use a different model from its parent.

Example:

```text
Main
GPT-5.x

├── Architecture
│   Claude
│
└── Local model test
    local model
```

Provider choice is thread-local configuration.

---

# 25. Attachments

Attachments made before a branch point should conceptually be available to descendants if they form part of the inherited context.

Attachments created inside a side thread must not become visible to:

- its parent
- siblings
- unrelated branches

unless explicitly shared.

The first implementation may retain Open WebUI's existing attachment behavior where feasible, but this isolation rule must ultimately hold.

---

# 26. MVP Requirements

The first useful version should implement only the essential branching workflow.

## Required

- Fork Open WebUI.
- Persist a parent-child relationship between threads.
- Persist the message from which each thread branched.
- Create a side thread from any message.
- Support branches of branches.
- Render a hierarchical thread tree.
- Switch between threads.
- Preserve every thread independently.
- Construct inherited context correctly.
- Prevent descendant/sibling pollution.
- Support arbitrarily deep nesting.
- Allow thread renaming.
- Allow thread deletion with descendant protection.
- Preserve existing Open WebUI chat capabilities as much as possible.

## Not required initially

- branch merging
- automatic knowledge sharing between branches
- AI-generated cross-thread summaries
- drag/drop tree organization
- collaboration
- thread sharing
- graph visualization
- semantic retrieval across threads
- automatic branch classification

---

# 27. Example Acceptance Test

Create the following conversation:

```text
Main

M1: User asks about starting a company
M2: Assistant responds
M3: User discusses positioning
M4: Assistant responds
```

From M4 create:

```text
Thread A: Pricing
```

Add:

```text
A1
A2
A3
```

From A2 create:

```text
Thread B: Competitors
```

Add:

```text
B1
B2
```

Return to Main and add:

```text
M5
M6
```

Expected thread tree:

```text
Main
│
└── Pricing
    │
    └── Competitors
```

Expected context for Main:

```text
M1
M2
M3
M4
M5
M6
```

Expected context for Pricing after A3:

```text
M1
M2
M3
M4
A1
A2
A3
```

Expected context for Competitors:

```text
M1
M2
M3
M4
A1
A2
B1
B2
```

Competitors must **not** receive:

```text
A3
M5
M6
```

Main must **not** receive:

```text
A1
A2
A3
B1
B2
```

This behavior should be covered by automated tests because it represents the application's fundamental invariant.

---

# 28. Fundamental Invariants

The implementation must preserve these invariants:

### Invariant 1

Every non-root thread has exactly one parent thread.

### Invariant 2

Every non-root thread has exactly one branch point.

### Invariant 3

A child inherits ancestor context only up to each corresponding branch point.

### Invariant 4

Descendant messages never implicitly modify ancestor context.

### Invariant 5

Sibling branches never implicitly see each other's messages.

### Invariant 6

Conversation history remains persisted independently of current LLM context limits.

### Invariant 7

Navigating between branches never destroys or rewrite existing conversation history.

---

# 29. Design Principle

The application should make conversations feel like a navigable body of thought rather than a list of isolated chats.

The central mental model is:

```text
One subject
    ↓
One evolving conversation tree
```

rather than:

```text
Many unrelated chats
```

The user should be able to explore ideas deeply, follow tangents, return to previous reasoning paths, and continue the main discussion without losing context or contaminating it.

The result should essentially provide **Git-like branching for persistent AI conversations**, built on top of Open WebUI's existing chat infrastructure.
