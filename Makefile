# ThinkVault Makefile

PROJECT_ROOT := $(dir $(realpath $(firstword $(MAKEFILE_LIST))))

.PHONY: install test serve clean lint

# 安装依赖
install:
	pip install -r requirements.txt

# 安装 GPU 版本（需要 CUDA）
install-gpu:
	pip install -r requirements.txt
	pip install torch --index-url https://download.pytorch.org/whl/cu121

# 运行所有测试
test:
	cd $(PROJECT_ROOT) && python -m pytest test/ -v --tb=short

# 单独运行某个测试
test-parser:
	cd $(PROJECT_ROOT) && python test/test_parser.py

test-chunker:
	cd $(PROJECT_ROOT) && python test/test_chunker.py

test-storage:
	cd $(PROJECT_ROOT) && python test/test_storage.py

test-hardware:
	cd $(PROJECT_ROOT) && python test/test_hardware.py

test-retriever:
	cd $(PROJECT_ROOT) && python test/test_retriever.py

# 启动开发服务器
serve:
	cd $(PROJECT_ROOT) && python -m thinkvault.cli serve

# 硬件检测
hardware:
	cd $(PROJECT_ROOT) && python -m thinkvault.cli hardware

# 代码检查
lint:
	cd $(PROJECT_ROOT) && python -m ruff check thinkvault/ test/

# 清理临时文件
clean:
	cd $(PROJECT_ROOT) && python -c "import shutil,pathlib; [shutil.rmtree(d,True) for d in ['thinkvault/temp_uploads','test/test_output','logs'] if pathlib.Path(d).exists()]; print('cleaned')"
