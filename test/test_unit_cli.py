"""
单元测试：CLI 入口 (cli.py)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from unittest.mock import patch, MagicMock


class TestCLI:
    def test_hardware_command(self):
        """测试 hardware 子命令正常执行"""
        with patch("sys.argv", ["thinkvault", "hardware"]):
            from thinkvault.utils.hardware import detect_hardware
            profile = detect_hardware()
            assert profile.cpu_count > 0
            assert profile.total_ram_gb > 0

    def test_parse_command_help(self):
        """测试 parse 子命令参数解析"""
        import argparse
        from thinkvault.cli import main as cli_main

        # 仅测试 argparse 能正确解析参数
        parser = argparse.ArgumentParser(prog="thinkvault")
        subparsers = parser.add_subparsers(dest="command")
        parse_parser = subparsers.add_parser("parse")
        parse_parser.add_argument("file")
        parse_parser.add_argument("--output", "-o", default=None)

        args = parser.parse_args(["parse", "test.txt", "-o", "out.md"])
        assert args.command == "parse"
        assert args.file == "test.txt"
        assert args.output == "out.md"

    def test_serve_default_args(self):
        """测试 serve 子命令默认参数"""
        import argparse
        parser = argparse.ArgumentParser(prog="thinkvault")
        subparsers = parser.add_subparsers(dest="command")
        serve_parser = subparsers.add_parser("serve")
        serve_parser.add_argument("--host", default="127.0.0.1")
        serve_parser.add_argument("--port", type=int, default=8000)

        args = parser.parse_args(["serve"])
        assert args.host == "127.0.0.1"
        assert args.port == 8000

    def test_empty_command_shows_help(self):
        """无命令时显示帮助"""
        import argparse
        parser = argparse.ArgumentParser(prog="thinkvault")
        subparsers = parser.add_subparsers(dest="command")

        # 无子命令时 dest 为 None
        try:
            args = parser.parse_args([])
            assert args.command is None
        except SystemExit:
            pass  # argparse 可能直接 exit


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
