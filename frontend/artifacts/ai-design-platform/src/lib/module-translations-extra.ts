type ModuleTranslationEntry = {
  label: string;
  description: string;
};

/**
 * 接口注释：
 * 这里补的是“模块名 + 模块说明”这组静态文案。
 * 它和页面按钮文案不是一套数据，所以单独拆出来，避免 i18n 主文件太难维护。
 */
export const extraModuleTranslations: Record<
  string,
  Partial<Record<"ja" | "ko" | "ru" | "fr" | "de", ModuleTranslationEntry>>
> = {
  "user-system": {
    ja: { label: "ユーザーシステム", description: "ユーザー登録、サインイン、アクセス制御。" },
    ko: { label: "사용자 시스템", description: "사용자 가입, 로그인 및 접근 제어." },
    ru: { label: "Пользовательская система", description: "Регистрация пользователей, вход и управление доступом." },
    fr: { label: "Système utilisateur", description: "Inscription, connexion et contrôle d’accès des utilisateurs." },
    de: { label: "Benutzersystem", description: "Benutzerregistrierung, Anmeldung und Zugriffskontrolle." },
  },
  "customer-management": {
    ja: { label: "顧客管理", description: "顧客プロフィール、リード、アカウント記録、ライフサイクル追跡。" },
    ko: { label: "고객 관리", description: "고객 프로필, 리드, 계정 기록 및 라이프사이클 추적." },
    ru: { label: "Управление клиентами", description: "Профили клиентов, лиды, учётные записи и отслеживание жизненного цикла." },
    fr: { label: "Gestion client", description: "Profils clients, prospects, comptes et suivi du cycle de vie." },
    de: { label: "Kundenverwaltung", description: "Kundenprofile, Leads, Kontodatensätze und Lebenszyklusverfolgung." },
  },
  "workflow-automation": {
    ja: { label: "ワークフロー自動化", description: "タスク振り分け、承認、状態遷移、プロセス自動化。" },
    ko: { label: "워크플로 자동화", description: "작업 라우팅, 승인, 상태 전환 및 프로세스 자동화." },
    ru: { label: "Автоматизация workflow", description: "Маршрутизация задач, согласование, смена состояний и автоматизация процессов." },
    fr: { label: "Automatisation des workflows", description: "Routage des tâches, validations, transitions d’état et automatisation des processus." },
    de: { label: "Workflow-Automatisierung", description: "Aufgabenrouting, Freigaben, Statuswechsel und Prozessautomatisierung." },
  },
  "reporting-analytics": {
    ja: { label: "レポートと分析", description: "ダッシュボード、KPI 追跡、レポート、運用インサイト。" },
    ko: { label: "리포트 및 분석", description: "대시보드, KPI 추적, 리포트 및 운영 인사이트." },
    ru: { label: "Отчётность и аналитика", description: "Дашборды, отслеживание KPI, отчёты и операционные инсайты." },
    fr: { label: "Rapports et analyses", description: "Tableaux de bord, suivi des KPI, rapports et analyses opérationnelles." },
    de: { label: "Reporting & Analyse", description: "Dashboards, KPI-Tracking, Berichte und operative Einblicke." },
  },
  "commerce-operations": {
    ja: { label: "コマース運用", description: "カタログ、カート、チェックアウト、支払い、フルフィルメントの流れ。" },
    ko: { label: "커머스 운영", description: "카탈로그, 장바구니, 결제, 지불 및 이행 흐름." },
    ru: { label: "Коммерческие операции", description: "Каталог, корзина, оформление заказа, оплата и процессы исполнения." },
    fr: { label: "Opérations commerciales", description: "Catalogue, panier, paiement et flux d’exécution des commandes." },
    de: { label: "Commerce-Betrieb", description: "Katalog, Warenkorb, Checkout, Zahlung und Fulfillment-Abläufe." },
  },
  "content-management": {
    ja: { label: "コンテンツ管理", description: "コンテンツ公開、構造化編集、レビューのワークフロー。" },
    ko: { label: "콘텐츠 관리", description: "콘텐츠 발행, 구조화 편집 및 검토 워크플로." },
    ru: { label: "Управление контентом", description: "Публикация контента, структурированное редактирование и процессы проверки." },
    fr: { label: "Gestion de contenu", description: "Publication de contenu, édition structurée et workflows de revue." },
    de: { label: "Content-Management", description: "Content-Veröffentlichung, strukturierte Bearbeitung und Review-Workflows." },
  },
  "document-management": {
    ja: { label: "ドキュメント管理", description: "ドキュメント保管、タグ付け、レビュー、バージョン連携。" },
    ko: { label: "문서 관리", description: "문서 저장, 태깅, 검토 및 버전 기반 협업." },
    ru: { label: "Управление документами", description: "Хранение документов, теги, проверка и версионное взаимодействие." },
    fr: { label: "Gestion documentaire", description: "Stockage des documents, tags, revue et collaboration avec versions." },
    de: { label: "Dokumentenverwaltung", description: "Dokumentspeicherung, Tagging, Review und versionsbewusste Zusammenarbeit." },
  },
  "inventory-operations": {
    ja: { label: "在庫運用", description: "在庫可視化、在庫更新、供給計画のワークフロー。" },
    ko: { label: "재고 운영", description: "재고 가시성, 재고 업데이트 및 공급 계획 워크플로." },
    ru: { label: "Складские операции", description: "Видимость запасов, обновление остатков и процессы планирования поставок." },
    fr: { label: "Opérations d’inventaire", description: "Visibilité des stocks, mises à jour et workflows de planification des approvisionnements." },
    de: { label: "Bestandsbetrieb", description: "Bestandsübersicht, Bestandsaktualisierungen und Planungsabläufe." },
  },
  "scheduling-booking": {
    ja: { label: "スケジュールと予約", description: "カレンダー調整、予約、時間ベースの空き状況管理。" },
    ko: { label: "일정 및 예약", description: "캘린더 조정, 예약 및 시간 기반 가용성 관리." },
    ru: { label: "Планирование и бронирование", description: "Календарная координация, бронирование и управление доступностью по времени." },
    fr: { label: "Planification et réservation", description: "Coordination de calendrier, réservations et gestion des disponibilités." },
    de: { label: "Planung & Buchung", description: "Kalenderabstimmung, Reservierungen und zeitbasierte Verfügbarkeitsverwaltung." },
  },
  "ai-assistant-workspace": {
    ja: { label: "AI アシスタント作業台", description: "Agent 会話、プロンプト実行、AI によるタスク支援。" },
    ko: { label: "AI 어시스턴트 워크스페이스", description: "Agent 대화, 프롬프트 실행 및 AI 기반 작업 지원." },
    ru: { label: "Рабочее пространство AI-ассистента", description: "Диалоги с агентами, выполнение промптов и помощь AI в задачах." },
    fr: { label: "Espace assistant IA", description: "Conversations avec des agents, exécution de prompts et assistance par IA." },
    de: { label: "AI-Assistent-Workspace", description: "Agentengespräche, Prompt-Ausführung und KI-gestützte Aufgabenhilfe." },
  },
  collaboration: {
    ja: { label: "コラボレーション", description: "共有コメント、メンション、通知、レビュー調整。" },
    ko: { label: "협업", description: "공유 댓글, 멘션, 알림 및 검토 조율." },
    ru: { label: "Совместная работа", description: "Общие комментарии, упоминания, уведомления и координация проверок." },
    fr: { label: "Collaboration", description: "Commentaires partagés, mentions, notifications et coordination des revues." },
    de: { label: "Zusammenarbeit", description: "Geteilte Kommentare, Erwähnungen, Benachrichtigungen und Review-Abstimmung." },
  },
  "core-business-workflow": {
    ja: { label: "中核業務フロー", description: "業務を入力から完了まで進める主要ドメインフロー。" },
    ko: { label: "핵심 비즈니스 워크플로", description: "업무를 입력에서 완료까지 이동시키는 핵심 도메인 흐름." },
    ru: { label: "Ключевой бизнес-процесс", description: "Основной доменный процесс, который ведёт бизнес от входа до завершения." },
    fr: { label: "Workflow métier principal", description: "Le flux métier central qui fait avancer le processus de bout en bout." },
    de: { label: "Kern-Geschäftsworkflow", description: "Der zentrale Domänenablauf, der den Prozess von der Eingabe bis zum Abschluss führt." },
  },
  "admin-console": {
    ja: { label: "管理コンソール", description: "プロジェクト、データ、設定を一元管理。" },
    ko: { label: "관리 콘솔", description: "프로젝트, 데이터 및 설정을 중앙에서 관리." },
    ru: { label: "Административная консоль", description: "Централизованное управление проектами, данными и конфигурацией." },
    fr: { label: "Console d’administration", description: "Gestion centralisée des projets, des données et de la configuration." },
    de: { label: "Admin-Konsole", description: "Zentrale Verwaltung von Projekten, Daten und Konfiguration." },
  },
};
