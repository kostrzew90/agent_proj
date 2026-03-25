"""Tests for language parsers."""

from ai_repo.parsers.python_parser import parse_python
from ai_repo.parsers.yaml_parser import parse_yaml
from ai_repo.parsers.sql_parser import parse_sql
from ai_repo.parsers.dockerfile_parser import parse_dockerfile
from ai_repo.parsers.generic_parser import parse_generic


# ── Python parser ────────────────────────────────────────────────────────

class TestPythonParser:

    def test_extracts_class(self):
        source = '''
class MyClass:
    """A test class."""
    pass
'''
        result = parse_python("test.py", source)
        classes = [s for s in result.symbols if s.kind == "class"]
        assert len(classes) == 1
        assert classes[0].name == "MyClass"
        assert classes[0].docstring == "A test class."

    def test_extracts_function(self):
        source = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        result = parse_python("test.py", source)
        funcs = [s for s in result.symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"
        assert "name: str" in funcs[0].signature
        assert "-> str" in funcs[0].signature

    def test_extracts_imports(self):
        source = '''
import os
from pathlib import Path
'''
        result = parse_python("test.py", source)
        imports = [s for s in result.symbols if s.kind == "import"]
        assert len(imports) == 2
        names = {s.name for s in imports}
        assert "os" in names
        assert "Path" in names

    def test_extracts_inheritance_edges(self):
        source = '''
class Base:
    pass

class Child(Base):
    pass
'''
        result = parse_python("test.py", source)
        inheritance = [e for e in result.edges if e.edge_type == "inheritance"]
        assert len(inheritance) == 1
        assert inheritance[0].src_name == "Child"
        assert inheritance[0].dst_name == "Base"

    def test_extracts_call_edges(self):
        source = '''
def main():
    result = process_data()
'''
        result = parse_python("test.py", source)
        calls = [e for e in result.edges if e.edge_type == "call"]
        assert any(c.dst_name == "process_data" for c in calls)

    def test_handles_syntax_error(self):
        source = "def broken(:\n    pass"
        result = parse_python("bad.py", source)
        assert result.symbols == []
        assert result.edges == []


# ── YAML parser ──────────────────────────────────────────────────────────

class TestYAMLParser:

    def test_docker_compose_services(self):
        source = '''
services:
  web:
    image: nginx:latest
    depends_on:
      - db
  db:
    image: postgres:16
    ports:
      - "5432:5432"
'''
        result = parse_yaml("docker-compose.yml", source)
        services = [s for s in result.symbols if s.kind == "service"]
        assert len(services) == 2
        names = {s.name for s in services}
        assert "web" in names
        assert "db" in names

        deps = [e for e in result.edges if e.edge_type == "depends_on"]
        assert len(deps) == 1
        assert deps[0].src_name == "web"
        assert deps[0].dst_name == "db"

    def test_generic_yaml_config_keys(self):
        source = '''
database:
  host: localhost
  port: 5432
api:
  port: 8000
'''
        result = parse_yaml("config.yaml", source)
        keys = [s for s in result.symbols if s.kind == "config_key"]
        assert len(keys) == 2
        names = {s.name for s in keys}
        assert "database" in names
        assert "api" in names

    def test_invalid_yaml(self):
        source = "::invalid: {yaml: ["
        result = parse_yaml("bad.yaml", source)
        assert result.symbols == []


# ── SQL parser ───────────────────────────────────────────────────────────

class TestSQLParser:

    def test_extracts_tables(self):
        source = '''
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id)
);
'''
        result = parse_sql("schema.sql", source)
        tables = [s for s in result.symbols if s.kind == "table"]
        assert len(tables) == 2
        names = {s.name for s in tables}
        assert "users" in names
        assert "orders" in names

    def test_extracts_foreign_keys(self):
        source = '''
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id)
);
'''
        result = parse_sql("schema.sql", source)
        deps = [e for e in result.edges if e.edge_type == "depends_on"]
        assert len(deps) == 1
        assert deps[0].src_name == "orders"
        assert deps[0].dst_name == "users"

    def test_extracts_indexes(self):
        source = "CREATE INDEX idx_users_name ON users (name);"
        result = parse_sql("schema.sql", source)
        indexes = [s for s in result.symbols if s.kind == "index"]
        assert len(indexes) == 1
        assert indexes[0].name == "idx_users_name"
        assert "ON users" in indexes[0].signature


# ── Dockerfile parser ────────────────────────────────────────────────────

class TestDockerfileParser:

    def test_extracts_from_stage(self):
        source = "FROM python:3.12-slim AS builder"
        result = parse_dockerfile("Dockerfile", source)
        stages = [s for s in result.symbols if s.kind == "docker_stage"]
        assert len(stages) == 1
        assert stages[0].name == "stage:builder"
        assert stages[0].signature == "python:3.12-slim"

    def test_extracts_expose(self):
        source = "EXPOSE 8080"
        result = parse_dockerfile("Dockerfile", source)
        endpoints = [s for s in result.symbols if s.kind == "endpoint"]
        assert len(endpoints) == 1
        assert endpoints[0].name == "port:8080"

    def test_extracts_entrypoint(self):
        source = 'ENTRYPOINT ["python", "app.py"]'
        result = parse_dockerfile("Dockerfile", source)
        eps = [s for s in result.symbols if s.kind == "entrypoint"]
        assert len(eps) == 1
        assert eps[0].name == "entrypoint"


# ── Generic parser ───────────────────────────────────────────────────────

class TestGenericParser:

    def test_requirements_txt(self):
        source = '''
# Web
fastapi>=0.115.0
uvicorn[standard]>=0.34.0
'''
        result = parse_generic("requirements.txt", source)
        deps = [s for s in result.symbols if s.kind == "dependency"]
        assert len(deps) == 2
        names = {s.name for s in deps}
        assert "fastapi" in names
        assert "uvicorn" in names

    def test_env_file(self):
        source = '''
DB_HOST=localhost
DB_PORT=5432
# comment
SECRET_KEY=abc123
'''
        result = parse_generic(".env", source)
        vars_ = [s for s in result.symbols if s.kind == "variable"]
        assert len(vars_) == 3
        names = {s.name for s in vars_}
        assert "DB_HOST" in names
        assert "SECRET_KEY" in names

    def test_markdown_headings(self):
        source = '''
# Title
## Section One
### Subsection
## Section Two
'''
        result = parse_generic("README.md", source)
        h1 = [s for s in result.symbols if s.kind == "heading_h1"]
        h2 = [s for s in result.symbols if s.kind == "heading_h2"]
        h3 = [s for s in result.symbols if s.kind == "heading_h3"]
        assert len(h1) == 1
        assert len(h2) == 2
        assert len(h3) == 1
