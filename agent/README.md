# 🧠 iSoftDevAgents: Agents for Intelligent Software Development

## 📌 Overview
This repository aims to build a suite of intelligent agents for **requirements development**, **software architecture design**, and **code generation**, developed under the **CrewAI** framework.  
Each agent focuses on a specific phase of intelligent software engineering, enabling collaborative automation across the entire development lifecycle.

---

## ⚙️ Development Framework: CrewAI

All contributors **must use the same CrewAI framework version** to ensure compatibility and stable agent interactions.

```bash
crewai == 1.2.0
crewai-tools == 1.2.0
```

## 🔧 Install dependencies
Using requirements.txt:

```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install crewai==1.2.0 crewai-tools==1.2.0
```

## 🧩 Repository Structure
```bash
├── Requirements Agent/        # Requirements Development Agent
├── Architecture Agent/        # Software Architecture Agent
├── Coding Agent/              # Code and Test Generation Agents
├── shared/              # Shared tools, prompts, and utilities
├── tests/               # Unit and integration tests
├── README.md
└── requirements.txt
```
## 👥 Collaboration Rules

1. **Branch Policy**

    ❌ Do **not** commit directly to `main` branch.  

    ✅ Each contributor should create and work on their own branch:
    ```bash
    git checkout -b <yourname>-dev
    ```
    Example:
    ```bash
    git checkout -b weisong-dev
    ```

---

2. **Pull Request Workflow**

    1. Commit and push your changes to your branch:
        ```bash
        git add .
        git commit -m "Add architecture agent prototype"
        git push origin weisong-dev
        ```

    2. Go to GitHub → open a **Pull Request (PR)** → request review before merging into `main`.

---

3. **Sync with Main**

    Keep your branch updated with the latest main branch:
    ```bash
    git checkout main
    git pull origin main
    git checkout weisong-dev
    git merge main
    ```

---

4. **Commit Message Convention**

    Use clear and consistent commit messages:
    ```bash
    feat: add unit test generation agent
    fix: resolve CrewAI initialization issue
    docs: update architecture design section
    refactor: clean up agent pipeline
    ```

---

5. **Version Control Notes**

    - Keep branch names meaningful (e.g., `weisong-dev`, `requirements-agent-dev`)  
    - Create pull requests frequently rather than making large merges  
    - All major changes must go through PR review before merging


