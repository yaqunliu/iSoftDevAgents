/**
 * 接口注释：
 * 官网落地页（/landing、/terms、/privacy）的全部文案。
 *
 * 设计注释：
 * 单独拆文件的理由和 i18n-extra-locales.ts 一致——避免 i18n 主文件继续膨胀。
 * 这里只填 en：官网面向企业客户、以新加坡为出海枢纽服务国际市场，英文是主语言。
 * i18n 已配置 fallbackLng: "en"，所以用户即使把产品界面切成日语或中文，
 * 官网也会稳定回落到英文，不会出现空白的 translation key。
 * 以后要加语言，在这里按 locale 追加同名 key 即可，不需要改任何组件。
 */

/**
 * 教学注释：
 * 文案里所有关于产品能力的陈述都必须能在产品里找到对应实现。
 * 特别是 ticker 那六个数据位——参考稿原本写的是 "14.2k Hours Reclaimed"、
 * "∞ Human Potential" 这类营销数字，企业买家看到会立刻要求提供证明。
 * 这里全部换成产品的结构性事实（几个 Agent、几个视图、什么技术栈），
 * 不需要任何运营数据支撑，也不会在销售环节被反问。
 */
export const landingLocaleResources = {
  en: {
    // ---------- 顶部导航 ----------
    "lp.nav.pipeline": "Agents",
    "lp.nav.observability": "Observability",
    "lp.nav.stack": "Stack",
    "lp.nav.company": "Company",
    "lp.nav.contact": "Contact",
    "lp.nav.login": "Log in",
    "lp.nav.skipToContent": "Skip to main content",
    "lp.nav.openMenu": "Open navigation",
    "lp.nav.closeMenu": "Close navigation",

    // ---------- Hero ----------
    "lp.hero.eyebrow": "Multi-agent software delivery",
    "lp.hero.title": "Five agents. One reviewable delivery trail.",
    "lp.hero.body":
      "Write what you need in plain language. gmonkey.ai runs five specialist agents in sequence — requirements, architecture, UI, code, tests — and every handoff leaves an artifact you can open, review, and correct.",
    "lp.hero.primaryCta": "Open the platform",
    "lp.hero.secondaryCta": "See how it works",
    "lp.hero.statusLabel": "Requirements locked · four stages running unattended",

    // ---------- Ticker（结构性事实，非营销数字） ----------
    "lp.ticker.agents.value": "5",
    "lp.ticker.agents.label": "Specialist agents",
    "lp.ticker.views.value": "4",
    "lp.ticker.views.label": "Fixed review views",
    "lp.ticker.artifacts.value": "6",
    "lp.ticker.artifacts.label": "Artifact types",
    "lp.ticker.trace.value": "100%",
    "lp.ticker.trace.label": "LLM I/O retained",
    "lp.ticker.models.value": "Any",
    "lp.ticker.models.label": "OpenAI-compatible model",
    "lp.ticker.deploy.value": "1",
    "lp.ticker.deploy.label": "Command to deploy",

    // ---------- 五 Agent 流水线 ----------
    "lp.pipeline.eyebrow": "The relay",
    "lp.pipeline.title": "Each agent runs as its own process, with its own timeout budget.",
    "lp.pipeline.body":
      "Stages hand off in a fixed order. Artifacts are written straight to the filesystem, so nothing lives only inside a model context.",
    "lp.pipeline.progressLabel": "Pipeline progress",

    "lp.pipeline.requirements.name": "Requirements Agent",
    "lp.pipeline.requirements.summary":
      "Turns the prompt into a specification you can argue with — scope, modules, and acceptance criteria.",
    "lp.pipeline.requirements.artifact.srs": "SRS",
    "lp.pipeline.requirements.artifact.prd": "PRD",

    "lp.pipeline.architecture.name": "Architecture Agent",
    "lp.pipeline.architecture.summary":
      "Proposes the system design and draws it, so structural decisions are visible before any code exists.",
    "lp.pipeline.architecture.artifact.systemDesign": "System design",
    "lp.pipeline.architecture.artifact.diagram": "Architecture diagram",

    "lp.pipeline.ui.name": "UI Agent",
    "lp.pipeline.ui.summary":
      "Produces a high-fidelity prototype — reviewable as a screen, not as a description of a screen.",
    "lp.pipeline.ui.artifact.prototype": "High-fidelity prototype",

    "lp.pipeline.coding.name": "Coding Agent",
    "lp.pipeline.coding.summary":
      "Generates the full code workspace, organised as a project rather than as loose snippets.",
    "lp.pipeline.coding.artifact.workspace": "Code workspace",

    "lp.pipeline.testing.name": "Testing Agent",
    "lp.pipeline.testing.summary":
      "Fills in the test cases the earlier stages implied but did not write.",
    "lp.pipeline.testing.artifact.testCases": "Test cases",

    "lp.pipeline.state.pending": "Queued",
    "lp.pipeline.state.running": "Running",
    "lp.pipeline.state.done": "Delivered",
    "lp.pipeline.artifactsLabel": "Writes",

    // ---------- 深色展示块 ----------
    "lp.showcase.eyebrow": "Artifacts, not transcripts",
    "lp.showcase.title": "Everything lands on the filesystem.",
    "lp.showcase.body":
      "Each stage writes real files as it goes. Nothing important exists only inside a model's context window, which is what makes the run reviewable after the fact.",

    // ---------- 人在环中 ----------
    "lp.control.eyebrow": "Human in the loop",
    "lp.control.title": "Correct an agent mid-run. Nothing gets re-run.",
    "lp.control.body":
      "An agent pauses at every key artifact and reports. Approve it and the relay continues. See something wrong and one sentence is enough — your feedback is injected into the running agent and takes effect where it stands.",
    "lp.control.step1.title": "The agent pauses and reports",
    "lp.control.step1.body": "Every key artifact stops for review before the next stage starts.",
    "lp.control.step2.title": "You write one line",
    "lp.control.step2.body":
      "Say what to change. No forms, no re-prompting, no restating the original requirement.",
    "lp.control.step3.title": "It applies in place",
    "lp.control.step3.body":
      "Feedback reaches the agent already running. The stage is not restarted and earlier work is not discarded.",
    "lp.control.footnote":
      "Once requirements are locked, the remaining four stages run unattended — there is nothing to sit and watch.",

    // ---------- 可观测性（深色区块） ----------
    "lp.observability.eyebrow": "Observability",
    "lp.observability.title": "When it fails, you get a debug package — not a shrug.",
    "lp.observability.body":
      "Step cards show live status, elapsed time, and output files per stage. Token usage is attributed step by step. Every LLM input and output is retained in full.",
    "lp.observability.panelTitle": "Run trace",
    "lp.observability.panelSubtitle": "Live status per stage",
    "lp.observability.feature.steps.title": "Step cards, live",
    "lp.observability.feature.steps.body":
      "Status, duration, and the files each stage produced — visible while it runs, not reconstructed afterwards.",
    "lp.observability.feature.tokens.title": "Token usage per step",
    "lp.observability.feature.tokens.body":
      "Attributed to the individual step, so cost is traceable to the stage that caused it.",
    "lp.observability.feature.trace.title": "Full LLM I/O retained",
    "lp.observability.feature.trace.body":
      "Every prompt and completion is kept, so a questionable output can be read back rather than guessed at.",
    "lp.observability.feature.debug.title": "Automatic debug package",
    "lp.observability.feature.debug.body":
      "When an agent fails, the platform packages the inputs, stdout, stderr, and whatever artifacts already exist.",
    "lp.observability.metric.elapsed": "Elapsed",
    "lp.observability.metric.tokens": "Tokens",
    "lp.observability.metric.files": "Files",
    // 原因注释：面板里的耗时和 token 数是为了说明"步骤卡长什么样"而摆的示例值，
    // 不是任何真实运行的性能数据。必须有这句声明，否则它会被当成性能承诺，
    // 在采购环节被要求提供基准测试报告。这句话不要删。
    "lp.observability.panelNote": "Illustration of the step cards — values are sample data.",

    // ---------- 四个固定视图 ----------
    "lp.views.eyebrow": "Structured output",
    "lp.views.title": "Dozens of files underneath. Four views on top.",
    "lp.views.body":
      "The agents may write a large number of files. The main panel always presents the same four views, so reviewers see a structured result instead of a directory listing.",
    "lp.views.prd.name": "PRD",
    "lp.views.prd.body": "Scope, modules, and acceptance criteria in reviewable form.",
    "lp.views.ui.name": "UI",
    "lp.views.ui.body": "The prototype, as a screen you can click through.",
    "lp.views.architecture.name": "Architecture",
    "lp.views.architecture.body": "System design and diagrams for structural review.",
    "lp.views.api.name": "API",
    "lp.views.api.body": "Interface surface, collected in one place.",

    // ---------- 技术栈与部署 ----------
    "lp.stack.eyebrow": "Stack & deployment",
    "lp.stack.title": "Deployable on infrastructure you already run.",
    "lp.stack.body":
      "No proprietary runtime and no single-vendor model dependency. The platform runs where your data is allowed to be.",
    "lp.stack.backend.label": "Backend",
    "lp.stack.backend.value": "FastAPI · PostgreSQL",
    "lp.stack.frontend.label": "Frontend",
    "lp.stack.frontend.value": "React",
    "lp.stack.models.label": "Models",
    "lp.stack.models.value": "Any OpenAI-compatible endpoint",
    "lp.stack.deploy.label": "Deployment",
    "lp.stack.deploy.value": "Docker Compose, single command",

    // ---------- Roadmap（明确标注未发布） ----------
    // ⚠️ eyebrow 的 "Roadmap"、body 结尾的 "Planned, not shipped:"、
    // 以及三条 item 的将来时，共同承担"这不是现货"的免责。
    // 标题旁原本还有一个 "In development — not yet available" 徽章，
    // 2026-09-03 按要求去掉了。改这几条文案时不要把将来时改成现在时。
    "lp.roadmap.eyebrow": "Roadmap",
    "lp.roadmap.title": "From code to something you can open.",
    "lp.roadmap.body":
      "The direction is to move the deliverable from source code to a running product. Planned, not shipped:",
    "lp.roadmap.item1.title": "Compilable project output",
    "lp.roadmap.item1.body":
      "Complete engineering code alongside its dependency manifest, configuration, database scripts, and build and start scripts.",
    "lp.roadmap.item2.title": "Sandbox build and run",
    "lp.roadmap.item2.body":
      "Output drops into an isolated sandbox that installs dependencies, builds, and runs it — producing a preview URL you can open.",
    "lp.roadmap.item3.title": "Generate, run, repair",
    "lp.roadmap.item3.body":
      "Runtime logs and test results from the sandbox feed back to the agents, closing the loop between generating code and knowing whether it works.",

    // ---------- 公司介绍 ----------
    "lp.company.eyebrow": "Company",
    "lp.company.title": "GorillaBits Tech Pte. Ltd.",
    "lp.company.incorporation": "Incorporated in Singapore · 29 July 2025",
    "lp.company.body1":
      "GorillaBits works across both the hardware and software links of the AI supply chain: sourcing, integration, and cross-border supply of AI infrastructure and compute hardware, and building AI application systems for enterprise customers.",
    "lp.company.body2":
      "Core team members come from international cloud and internet companies, with experience operating infrastructure at scale, delivering enterprise systems, and putting AI into production. That covers the full stack — chips, machines, and clusters through to models and applications — and, just as importantly, the trade-offs real deployments force between cost, stability, and compliance.",
    "lp.company.body3":
      "Singapore is both our headquarters and our gateway outward, serving Southeast Asia and wider international markets with integrated solutions spanning hardware selection, system build-out, and AI capability integration. We also take on AI advisory work and engineering-team capability building.",
    "lp.company.thesis.title": "Why we build this way",
    "lp.company.thesis.body":
      "The value of AI ultimately depends on whether it can be deployed into a specific business reliably and economically. We treat engineering reliability and delivery certainty as the core competency — rather than chasing developments at the model layer alone.",
    "lp.company.fact.hq.label": "Headquarters",
    "lp.company.fact.hq.value": "Singapore",
    "lp.company.fact.markets.label": "Markets",
    "lp.company.fact.markets.value": "Southeast Asia & international",
    "lp.company.fact.focus.label": "Focus",
    "lp.company.fact.focus.value": "AI infrastructure & enterprise AI systems",

    // ---------- CTA ----------
    "lp.cta.title": "See the delivery trail on your own requirement.",
    "lp.cta.body": "Write the requirement in plain language and review what comes back.",
    "lp.cta.primary": "Open the platform",
    "lp.cta.secondary": "Email us",

    // ---------- 页脚 ----------
    "lp.footer.product": "Product",
    "lp.footer.company": "Company",
    "lp.footer.legal": "Legal",
    "lp.footer.contact": "Contact",
    "lp.footer.support": "support@gmonkey.ai",
    "lp.footer.terms": "Terms of Service",
    "lp.footer.privacy": "Privacy Policy",
    "lp.footer.login": "Log in",
    "lp.footer.legalName": "GorillaBits Tech Pte. Ltd.",
    "lp.footer.incorporation": "Incorporated in Singapore, 29 July 2025",
    "lp.footer.rights": "All rights reserved.",
    "lp.footer.tagline": "Engineering reliability over model-layer novelty.",

    // ---------- 法务页公共部分 ----------
    "lp.legal.backToHome": "Back to home",
    "lp.legal.lastUpdated": "Last updated",
    "lp.legal.lastUpdatedValue": "3 September 2026",
    "lp.legal.contactPrompt": "Questions about this document?",

    // ---------- Contact 页 ----------
    "lp.contact.title": "Talk to the team behind the platform.",
    "lp.contact.intro":
      "Tell us what you are trying to ship and who is involved. We read every message ourselves — there is no sales queue in front of us.",
    "lp.contact.asideTitle": "Direct line",
    "lp.contact.asideBody":
      "If you would rather write from your own mail client, or need to attach documents, that address reaches the same people.",
    "lp.contact.responseTitle": "What happens next",
    "lp.contact.responseBody":
      "We reply from Singapore business hours. Technical questions go to an engineer rather than a rep, so the first answer is usually the useful one.",
    "lp.contact.entityTitle": "Registered entity",

    // 表单字段
    "lp.contact.form.legend": "Send a message",
    "lp.contact.form.name": "Name",
    "lp.contact.form.namePlaceholder": "Your name",
    "lp.contact.form.email": "Work email",
    "lp.contact.form.emailPlaceholder": "you@company.com",
    "lp.contact.form.company": "Company",
    "lp.contact.form.companyOptional": "optional",
    "lp.contact.form.companyPlaceholder": "Company name",
    "lp.contact.form.message": "Message",
    "lp.contact.form.messagePlaceholder":
      "What are you building, and what stage is it at?",
    "lp.contact.form.submit": "Send message",
    "lp.contact.form.submitting": "Sending…",
    "lp.contact.form.required": "Required",

    // 校验提示。key 后缀和 landing-contact-form.ts 的返回值一一对应。
    "lp.contact.error.nameRequired": "Please tell us your name.",
    "lp.contact.error.emailRequired": "Please add an email address so we can reply.",
    "lp.contact.error.emailInvalid": "That does not look like a complete email address.",
    "lp.contact.error.messageRequired": "Please add a short message.",
    "lp.contact.error.messageTooLong":
      "That message is longer than we can accept. Please trim it, or send it by email instead.",
    "lp.contact.error.summary": "Please check the highlighted fields.",

    // 成功态。
    // ⚠️ successEmailPrompt 那一行在表单接上真实后端之前不要删——
    // 现在提交并不会真的发出任何东西，这行邮箱是访客唯一真正能送达的通路。
    "lp.contact.success.title": "Thanks — your message is with us.",
    "lp.contact.success.body":
      "We will get back to you at the address you provided.",
    "lp.contact.success.emailPrompt": "You can also reach us directly at",
    "lp.contact.success.again": "Send another message",

    // ---------- Terms of Service ----------
    "lp.terms.title": "Terms of Service",
    "lp.terms.intro":
      "These terms govern access to and use of the gmonkey.ai platform operated by GorillaBits Tech Pte. Ltd., a company incorporated in Singapore. By creating an account or using the platform, you agree to these terms.",
    "lp.terms.s1.title": "1. The service",
    "lp.terms.s1.body":
      "gmonkey.ai is a multi-agent software development platform. You submit requirements in natural language and the platform runs a sequence of agents that generate artifacts including specifications, architecture documents, interface prototypes, source code, and tests. The service is provided for use by business customers.",
    "lp.terms.s2.title": "2. Accounts and access",
    "lp.terms.s2.body":
      "You are responsible for the accuracy of your account details, for keeping your credentials confidential, and for all activity that occurs under your account. Notify us promptly at support@gmonkey.ai if you believe your account has been accessed without authorisation. We may suspend access where we reasonably believe it is necessary to protect the platform or other customers.",
    "lp.terms.s3.title": "3. Your content and your rights in output",
    "lp.terms.s3.body":
      "You retain all rights in the requirements, documents, and other materials you submit. As between you and us, you own the artifacts the platform generates from your inputs. You grant us only the licence needed to operate the service — to process your inputs, run the agents, store the artifacts, and provide support.",
    "lp.terms.s4.title": "4. Acceptable use",
    "lp.terms.s4.body":
      "You may not use the platform to generate or distribute unlawful material, to infringe the rights of others, to attempt to breach or interfere with the platform's security or availability, or to reverse engineer the service other than to the extent permitted by applicable law.",
    "lp.terms.s5.title": "5. Third-party models and services",
    "lp.terms.s5.body":
      "The platform can be configured to use third-party, OpenAI-compatible model endpoints. Where you configure such an endpoint, your inputs will be transmitted to that provider and that provider's own terms and processing practices will apply to them. You are responsible for choosing endpoints appropriate to the sensitivity of your data.",
    "lp.terms.s6.title": "6. Generated output requires review",
    "lp.terms.s6.body":
      "Output is produced by automated systems and may contain errors, omissions, insecure patterns, or material unsuitable for your purpose. It is provided as a starting point for professional review, not as a substitute for it. You are responsible for reviewing, testing, and validating any artifact before relying on it or deploying it.",
    "lp.terms.s7.title": "7. Availability and changes",
    "lp.terms.s7.body":
      "We may modify, suspend, or discontinue features of the platform. Where a change materially reduces functionality you rely on, we will give reasonable notice where practicable. Any service levels that apply to you are those set out in a separate written agreement.",
    "lp.terms.s8.title": "8. Fees",
    "lp.terms.s8.body":
      "Where fees apply, they are set out in the order or written agreement between us. Unless that agreement says otherwise, fees exclude taxes and are non-refundable once the corresponding service has been provided.",
    "lp.terms.s9.title": "9. Confidentiality",
    "lp.terms.s9.body":
      "Each party may receive information the other treats as confidential. Each party will use the other's confidential information only to perform under these terms and will protect it with at least the care it applies to its own confidential information of similar importance.",
    "lp.terms.s10.title": "10. Disclaimers and limitation of liability",
    "lp.terms.s10.body":
      "To the maximum extent permitted by law, the platform is provided without warranties of any kind, whether express or implied, including implied warranties of merchantability, fitness for a particular purpose, and non-infringement. To the maximum extent permitted by law, neither party is liable for indirect, incidental, special, consequential, or punitive damages, or for lost profits, revenue, or data. Nothing in these terms limits liability that cannot be limited under applicable law.",
    "lp.terms.s11.title": "11. Term and termination",
    "lp.terms.s11.body":
      "You may stop using the platform at any time. Either party may terminate for material breach that remains uncured after a reasonable opportunity to fix it. On termination, your right to access the platform ends; you should export any artifacts you wish to keep before that point.",
    "lp.terms.s12.title": "12. Governing law",
    "lp.terms.s12.body":
      "These terms are governed by the laws of Singapore, and the courts of Singapore have exclusive jurisdiction over any dispute arising from them, without prejudice to any different dispute resolution mechanism agreed in a separate written agreement between us.",
    "lp.terms.s13.title": "13. Contact",
    "lp.terms.s13.body":
      "Questions about these terms can be sent to support@gmonkey.ai, addressed to GorillaBits Tech Pte. Ltd., Singapore.",

    // ---------- Privacy Policy ----------
    "lp.privacy.title": "Privacy Policy",
    "lp.privacy.intro":
      "This policy explains how GorillaBits Tech Pte. Ltd. handles personal data in connection with the gmonkey.ai platform. It is written with reference to Singapore's Personal Data Protection Act.",
    "lp.privacy.s1.title": "1. Data we handle",
    "lp.privacy.s1.body":
      "Account data: name, email address, and authentication credentials. Content data: the requirements you submit, the files you upload as references, and the artifacts the platform generates. Operational data: run records, step status and timing, token usage, retained LLM inputs and outputs, and error diagnostics including debug packages. Technical data: log records generated when you access the service.",
    "lp.privacy.s2.title": "2. Why we handle it",
    "lp.privacy.s2.body":
      "To provide and operate the platform; to authenticate you and secure accounts; to make runs observable and debuggable, which is a core function of the product; to provide support; to meet legal and accounting obligations; and to improve reliability. We do not sell personal data.",
    "lp.privacy.s3.title": "3. Retained model inputs and outputs",
    "lp.privacy.s3.body":
      "The platform retains LLM inputs and outputs in full, and packages inputs, stdout, stderr, and partial artifacts when an agent fails. This exists so that a run can be audited and diagnosed. It also means content you submit is stored beyond the moment of generation — please avoid submitting personal data that is not needed for the task.",
    "lp.privacy.s4.title": "4. Third-party model providers",
    "lp.privacy.s4.body":
      "Where the platform is configured to use a third-party, OpenAI-compatible endpoint, your submitted content is transmitted to that provider and handled under that provider's terms. Self-hosted deployments can be configured so that content does not leave your own infrastructure.",
    "lp.privacy.s5.title": "5. Disclosure",
    "lp.privacy.s5.body":
      "We disclose personal data to service providers who help us operate the platform, under obligations of confidentiality; where required by law or valid legal process; and in connection with a corporate transaction, subject to equivalent protection. We do not otherwise disclose your content.",
    "lp.privacy.s6.title": "6. International transfers",
    "lp.privacy.s6.body":
      "We are based in Singapore and serve international markets, so personal data may be processed outside your own jurisdiction. Where we transfer personal data out of Singapore, we take steps intended to ensure a comparable standard of protection to that required under Singapore law.",
    "lp.privacy.s7.title": "7. Security",
    "lp.privacy.s7.body":
      "We apply administrative and technical measures intended to protect personal data against unauthorised access, alteration, and loss. No method of transmission or storage is completely secure, and we cannot guarantee absolute security.",
    "lp.privacy.s8.title": "8. Retention",
    "lp.privacy.s8.body":
      "We keep personal data for as long as needed for the purposes above, and thereafter as required to meet legal, accounting, or dispute-resolution obligations. Run records and retained model traces follow the retention configured for your deployment.",
    "lp.privacy.s9.title": "9. Your rights",
    "lp.privacy.s9.body":
      "Subject to applicable law, you may request access to the personal data we hold about you, ask us to correct it, withdraw a consent you have given, or ask us to delete data we no longer have grounds to keep. Send requests to support@gmonkey.ai. We may need to verify your identity before acting.",
    "lp.privacy.s10.title": "10. Changes to this policy",
    "lp.privacy.s10.body":
      "We may update this policy. Where a change is material, we will take reasonable steps to notify you. The date at the top of this page reflects the current version.",
    "lp.privacy.s11.title": "11. Contact",
    "lp.privacy.s11.body":
      "Privacy questions and requests can be sent to support@gmonkey.ai, addressed to GorillaBits Tech Pte. Ltd., Singapore.",
  },
} as const;

export type LandingLocaleResources = typeof landingLocaleResources;
