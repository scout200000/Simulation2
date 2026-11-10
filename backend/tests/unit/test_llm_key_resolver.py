"""DeepSeek API Key 解析测试（进程环境 / Windows 用户变量）。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.main.config import settings


class DeepSeekKeyResolverTest(unittest.TestCase):
    def test_clean_secret_strips_whitespace_and_quotes(self):
        self.assertEqual(settings._clean_secret('  " sk-abc "  '), "sk-abc")
        self.assertEqual(settings._clean_secret("'sk-def'"), "sk-def")

    def test_process_env_wins(self):
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": "  sk-env  "}, clear=False
        ), patch.object(
            settings,
            "_windows_environment_values",
            return_value=[("user", "sk-user")],
        ):
            self.assertEqual(settings.get_deepseek_api_key(), "sk-env")
            self.assertEqual(settings.get_deepseek_api_key_source(), "process")

    def test_falls_back_to_windows_user_env(self):
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False
        ), patch.object(
            settings,
            "_windows_environment_values",
            return_value=[("user", "sk-user")],
        ):
            self.assertEqual(settings.get_deepseek_api_key(), "sk-user")
            self.assertEqual(settings.get_deepseek_api_key_source(), "user")

    def test_read_aura_credentials_file(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "Neo4j-123.txt"
            path.write_text(
                "NEO4J_URI=neo4j+s://123.databases.neo4j.io\n"
                "NEO4J_USERNAME=123\n"
                "NEO4J_PASSWORD=secret\n"
                "NEO4J_DATABASE=123\n",
                encoding="utf-8",
            )
            values = settings._read_neo4j_credentials(str(path))
        self.assertEqual(values["NEO4J_URI"], "neo4j+s://123.databases.neo4j.io")
        self.assertEqual(values["NEO4J_USERNAME"], "123")
        self.assertEqual(values["NEO4J_PASSWORD"], "secret")
        self.assertEqual(values["NEO4J_DATABASE"], "123")

    def test_none_when_no_source_has_key(self):
        with patch.dict(
            os.environ, {"DEEPSEEK_API_KEY": ""}, clear=False
        ), patch.object(
            settings, "_windows_environment_values", return_value=[]
        ):
            self.assertEqual(settings.get_deepseek_api_key(), "")
            self.assertEqual(settings.get_deepseek_api_key_source(), "none")


if __name__ == "__main__":
    unittest.main()
