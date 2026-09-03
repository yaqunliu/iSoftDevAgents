import sys
import unittest
from pathlib import Path

import yaml
import tomllib


BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class DockerDeploymentAssetsTests(unittest.TestCase):
    """
    接口注释：
    这组测试只验证仓库里最基础的 Docker 部署资产有没有齐。

    教学注释：
    这里不尝试真的启动容器，重点是先把“该有的文件”和“核心服务结构”
    钉住，避免后面有人删掉 compose / nginx / Dockerfile 还不自知。
    """

    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[3]
        self.compose_path = self.repo_root / "docker-compose.yml"
        self.backend_dockerfile = self.repo_root / "deploy" / "docker" / "backend.Dockerfile"
        self.web_dockerfile = self.repo_root / "deploy" / "docker" / "web.Dockerfile"
        self.nginx_conf = self.repo_root / "deploy" / "docker" / "nginx.conf"
        self.backend_env_example = self.repo_root / "deploy" / "docker" / "backend.env.example"
        self.run_local_script = self.repo_root / "deploy" / "docker" / "run-local.sh"
        self.platform_pyproject = self.repo_root / "agent" / "platform" / "pyproject.toml"
        self.architecture_agent_pyproject = self.repo_root / "agent" / "Architecture Agent" / "pyproject.toml"

    def test_deployment_assets_exist(self) -> None:
        self.assertTrue(self.compose_path.exists())
        self.assertTrue(self.backend_dockerfile.exists())
        self.assertTrue(self.web_dockerfile.exists())
        self.assertTrue(self.nginx_conf.exists())
        self.assertTrue(self.backend_env_example.exists())
        self.assertTrue(self.run_local_script.exists())

    def test_compose_declares_backend_web_and_persistent_backend_data(self) -> None:
        payload = yaml.safe_load(self.compose_path.read_text(encoding="utf-8"))

        services = payload.get("services") or {}
        self.assertIn("backend", services)
        self.assertIn("web", services)

        backend = services["backend"]
        backend_volumes = backend.get("volumes") or []
        self.assertTrue(
            any("platform-data" in str(item) for item in backend_volumes),
            "backend 服务必须挂载持久化数据卷，避免 app.db 和调试包丢失。",
        )

        web = services["web"]
        depends_on = web.get("depends_on") or {}
        self.assertIn("backend", depends_on)

    def test_compose_clears_host_specific_agent_python_paths_in_container(self) -> None:
        """
        设计注释：
        Docker 容器里不能直接复用宿主机的绝对路径。
        这里把几个最容易被本地 `.env` 污染的 Agent Python / site-packages 配置钉住，
        避免容器启动时误读宿主机路径，再退回到奇怪的自动探测流程。
        """

        payload = yaml.safe_load(self.compose_path.read_text(encoding="utf-8"))
        backend_env = (payload.get("services") or {}).get("backend", {}).get("environment") or {}

        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_REAGENT_PYTHON_BIN"), "")
        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_REAGENT_SITE_PACKAGES"), "")
        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_ARCH_AGENT_PYTHON_BIN"), "")
        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_CODING_AGENT_PYTHON_BIN"), "")
        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_CODING_AGENT_SITE_PACKAGES"), "")
        self.assertEqual(backend_env.get("ISOFTDEVAGENTS_TEST_AGENT_SITE_PACKAGES"), "")

    def test_run_local_prefers_docker_specific_env_files(self) -> None:
        """
        原因注释：
        本地直接跑后端和本地 Docker 测试是两套不同场景。
        Docker 启动脚本应该优先读 `deploy/docker` 目录下的私有 env 文件，
        避免把宿主机开发路径偷偷带进容器。
        """

        script_text = self.run_local_script.read_text(encoding="utf-8")
        self.assertIn('load_env_file "$REPO_ROOT/deploy/docker/backend.env.local"', script_text)
        self.assertIn('load_env_file "$REPO_ROOT/deploy/docker/backend.env"', script_text)

    def test_backend_image_installs_architecture_agent_runtime_dependencies(self) -> None:
        """
        原因注释：
        Architecture Agent 默认在 Docker 部署里就是启用的。
        如果共享后端环境里缺少它运行期直接 import 的依赖，
        线上就会等到运行到架构阶段才因为 `ModuleNotFoundError` 直接失败。
        """

        dockerfile_text = self.backend_dockerfile.read_text(encoding="utf-8")
        platform_payload = tomllib.loads(self.platform_pyproject.read_text(encoding="utf-8"))
        architecture_payload = tomllib.loads(self.architecture_agent_pyproject.read_text(encoding="utf-8"))
        platform_dependencies = platform_payload.get("project", {}).get("dependencies", [])
        architecture_dependencies = architecture_payload.get("project", {}).get("dependencies", [])

        self.assertIn("/tmp/platform-direct-requirements.txt", dockerfile_text)
        self.assertIn("pymongo==4.16.0", platform_dependencies)
        self.assertIn("pymongo==4.16.0", architecture_dependencies)
        self.assertIn("crewai[tools]==1.6.0", platform_dependencies)
        self.assertIn("crewai[tools]==1.6.0", architecture_dependencies)


if __name__ == "__main__":
    unittest.main()
