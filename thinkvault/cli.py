"""CLI 入口"""

import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        prog="thinkvault",
        description="ThinkVault 个人 AI 工作台",
    )
    subparsers = parser.add_subparsers(dest="command")

    # thinkvault serve
    serve_parser = subparsers.add_parser("serve", help="启动 API 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8000)

    # thinkvault hardware
    subparsers.add_parser("hardware", help="检测硬件配置")

    # thinkvault parse <file>
    parse_parser = subparsers.add_parser("parse", help="解析文档")
    parse_parser.add_argument("file", help="文档路径")
    parse_parser.add_argument("--output", "-o", default=None,
                              help="将解析结果保存到文件（支持 .txt / .md）")

    args = parser.parse_args()

    if args.command == "serve":
        from thinkvault.api.server import run_server
        run_server(host=args.host, port=args.port)

    elif args.command == "hardware":
        from thinkvault.utils.hardware import detect_hardware
        profile = detect_hardware()
        print(f"CPU 核心: {profile.cpu_count}")
        print(f"总内存: {profile.total_ram_gb} GB")
        print(f"可用内存: {profile.available_ram_gb} GB")
        print(f"GPU: {profile.gpu_name or '无'}")
        print(f"显存: {profile.vram_gb} GB" if profile.vram_gb else "")
        print(f"CUDA: {'可用' if profile.has_cuda else '不可用'}")
        print(f"推荐模型档位: {profile.recommended_model_tier}")
        spec = profile.recommended_model_spec
        print(f"推荐规格: {spec['params']} {spec['quant']}（{spec['description']}）")

    elif args.command == "parse":
        from thinkvault.core.parser import DocumentParser
        doc = DocumentParser.parse(args.file)
        if doc.parse_error:
            print(f"解析失败: {doc.parse_error}")
        else:
            output_lines = [
                f"文件: {doc.file_name}",
                f"类型: {doc.file_type}",
                f"段落数: {len(doc.paragraphs)}",
                f"页数: {doc.total_pages}" if doc.total_pages else "",
                "",
                f"全文预览:\n{doc.raw_text[:500]}",
            ]
            output_text = "\n".join(line for line in output_lines if line)

            if args.output:
                output_path = Path(args.output)
                ext = output_path.suffix.lower()
                if ext == ".md":
                    md_lines = [
                        f"# {doc.file_name}",
                        "",
                        f"- **类型**: {doc.file_type}",
                        f"- **段落数**: {len(doc.paragraphs)}",
                    ]
                    if doc.total_pages:
                        md_lines.append(f"- **页数**: {doc.total_pages}")
                    md_lines.append("")
                    md_lines.append("## 全文内容")
                    md_lines.append("")
                    md_lines.append(doc.raw_text)
                    output_path.write_text("\n".join(md_lines), encoding="utf-8")
                else:
                    output_path.write_text(output_text, encoding="utf-8")
                print(f"解析结果已保存到: {output_path}")
            else:
                print(output_text)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
