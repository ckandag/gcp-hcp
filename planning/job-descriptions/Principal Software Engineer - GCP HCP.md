**Principal Software Engineer - GCP Hosted Control Planes**
**Job Description**

**Job Summary**

Red Hat Engineering is looking for a Principal Software Engineer to join the GCP Hosted Control Planes (HCP) team. This team builds and operates a managed service delivering OpenShift Kubernetes clusters on Google Cloud Platform using HyperShift, hosting dense multi-tenant control planes on GKE infrastructure.

This role sits at the intersection of distributed systems architecture and a new engineering discipline. Our team has adopted an agent-first development methodology where AI coding agents are a primary production mechanism, and engineers function as harness engineers — designing the systems, constraints, and feedback loops that make agent-driven development reliable and scalable. As a Principal Engineer, you will not only work within this model but lead its evolution: defining the architectural boundaries agents must respect, designing the documentation architecture that serves as the agent knowledge base, building the enforcement mechanisms (custom linters, structural tests, CI gates) that prevent entropy, and mentoring the team in effective human-agent collaboration patterns.

You will lead architectural decisions for a platform spanning GKE host clusters, HyperShift control planes, GCP networking and identity, observability, and deployment automation. You'll exercise expert judgment in specifying intent for complex systems work, evaluating whether agent-produced implementations meet the bar for production managed services, and deciding when to invest in harness infrastructure versus direct implementation.

**Responsibilities**

* Lead the design of the GCP HCP platform architecture, including multi-region scalability, multi-tenancy and isolation, automated lifecycle management, and operational resilience
* Design and evolve the team's harness engineering infrastructure: the system of architectural constraints, custom linters, structural tests, CI gates, and feedback loops that enable AI agents to produce reliable work at scale
* Define and maintain the team's documentation architecture — a structured knowledge base that serves as the single source of truth for both agents and engineers, treating AGENTS.md as the table of contents with deep references into design documents, architecture decision records, and operational runbooks
* Decompose complex system goals into well-bounded building blocks suitable for agent-driven implementation; evaluate when agent-generated approaches are sound and when they introduce unacceptable risk
* Identify and address architectural drift, entropy, and emergent quality issues across a large, agent-maintained codebase — designing systematic "garbage collection" processes to fight decay
* Lead architectural discussions across the HyperShift project, Cluster API communities, GCP platform integrations, and internal Red Hat teams
* Establish and enforce patterns for secure, maintainable, and observable systems — defining the module boundaries, dependency hierarchies, and interface contracts that constrain the solution space for both humans and agents
* Mentor senior engineers in harness engineering practices: crafting effective specifications, designing structural constraints, building agent-friendly documentation, and developing critical review skills for agent output
* Define quality bars, test strategies, and operational readiness criteria for agent-produced features, collaborating with Product Management and technical support to ensure production standards are met
* Serve as an escalation point for complex customer issues and production incidents beyond front-line technical support, applying deep platform knowledge to diagnosis and resolution
* Participate in on-call rotations to support production managed services
* Maintain a visible technical leadership presence in the Kubernetes, OpenShift, and GCP communities

**Required Skills**

* 10+ years of software engineering experience with strong proficiency in Go
* Deep expertise in Kubernetes internals, including controller/operator patterns, API server architecture, and cluster lifecycle management
* Demonstrated experience making architectural decisions for large-scale distributed systems in production
* Experience with at least one major public cloud platform at depth (GCP preferred), including compute, networking, identity, and managed services
* Track record of defining and enforcing architectural standards, coding conventions, or structural constraints across a multi-engineer codebase
* Strong written communication skills — ability to produce precise, structured technical documentation that serves as executable context for AI agents and as durable reference for engineers
* Experience or demonstrated aptitude with AI-assisted development workflows, including critical evaluation of machine-generated code and understanding of how to design systems that AI agents can work within effectively
* Ability to lead and influence without direct authority, across teams and organizational boundaries
* Experience mentoring engineers at multiple levels

**Preferred Skills**

* Deep experience with GKE, GCP networking, GCP IAM, and Workload Identity Federation
* Experience with HyperShift, Cluster API, or multi-tenant Kubernetes hosting architectures
* Experience designing custom linters, static analysis frameworks, or architectural test suites
* Experience with infrastructure-as-code and GitOps tools (Terraform, Tekton, ArgoCD)
* Experience with observability at scale (Prometheus, Google Managed Prometheus, distributed tracing)
* Track record of contributions to open source projects, particularly in the Kubernetes ecosystem
* Experience designing or operating managed/hosted cloud services under SLA
* Experience designing documentation systems or context architectures for AI/LLM-based tools
* Familiarity with harness engineering practices: entropy management, constraint-as-multiplier design, agent feedback loops, and structured codebase context
