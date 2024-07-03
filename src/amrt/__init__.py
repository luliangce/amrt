import collections
import hashlib
import pathlib
import re
from dataclasses import dataclass, field
from io import TextIOWrapper

import typer
import yaml


@dataclass
class Expression:
    desc: str
    expression: str

    # 当一个表达式已经确认无误时，可以通过这个正则从结果中排除他
    known: list[str] = field(default_factory=list)

    _id = None
    _pattern = None
    _exclude_patterns = None

    @property
    def id(self):
        if not self._id:
            self._id = hashlib.md5(self.expression.encode("utf-8")).hexdigest()
        return self._id

    @property
    def pattern(self):
        if not self._pattern:
            try:
                self._pattern = re.compile(self.expression)
            except re.error:
                typer.echo(f"表达式错误：{self.expression}")
                raise
        return self._pattern

    def should_exclude(self, paragraph):
        if not self._exclude_patterns:
            self._exclude_patterns = [re.compile(i) for i in self.known]
        for pattern in self._exclude_patterns:
            if pattern.match(paragraph):
                return True
        return False


@dataclass
class ExpressionConfig:
    expressions: list[Expression]

    def __post_init__(self):
        self.expressions = [Expression(**i) for i in self.expressions]


def load_expression(yaml_file_path: pathlib.Path) -> ExpressionConfig:
    # 读取YAML文件
    with open(yaml_file_path, "r") as file:
        data = yaml.safe_load(file)
    return ExpressionConfig(**data)


def split_text(
    file: TextIOWrapper,
    regex_data: list[Expression],
):
    result: list[str, bool] = []

    def push(expression: Expression, lines: list[str]):
        nonlocal result
        if len(lines) < 2:
            return
        paragraph = "\n".join(lines)
        result.append((paragraph, expression.should_exclude(paragraph)))

    current_group = []
    current_regexp = None
    match_count = collections.defaultdict(int)
    for line in file:
        line = line.strip("\n")
        if not line:
            continue
        for regexp in regex_data:
            if regexp.pattern.match(line):
                match_count[regexp.id] += 1
                if len(current_group) > 1:
                    push(expression=current_regexp, lines=current_group)
                current_regexp = regexp
                current_group = [line]
                break
        else:
            current_group.append(line)

    if len(current_group) > 1 and current_regexp:
        push(expression=current_regexp, lines=current_group)

    return result, match_count


app = typer.Typer()


def report(
    counter: dict[str, int],
    expressions: list[Expression],
    result: list[tuple[str, bool]] | None = None,
):
    from rich.console import Console
    from rich.syntax import Syntax
    from rich.table import Table

    console = Console()
    table = Table("表达式", "描述", "出现次数", "百分比", title="表达式统计")

    total = sum(counter.values())
    if result:
        typer.echo(
            f"\n捕获到多行结果：{len(result)}/{total}个,其中有{sum(i[1] for i in result)}个已过滤\n"
        )
    final_expression_components = []
    for regexp in sorted(expressions, key=lambda x: counter[x.id], reverse=True):
        count = counter[regexp.id]
        table.add_row(
            *[
                Syntax(regexp.expression, lexer="perl"),
                regexp.desc,
                str(count),
                f"{count / total * 100:.2f}%",
            ]
        )
        final_expression_components.append(regexp.expression)
    console.print(table)

    final_expression = f'({"|".join(final_expression_components)}).*'
    typer.echo("按照出现频率拼接的首行表达式：\n")
    typer.echo(final_expression)
    typer.echo("\n")


@app.command()
def main(
    file: pathlib.Path,
    regexp_yaml_file: pathlib.Path,
    no_multi: bool = typer.Option(is_flag=True, default=False, help="不显示多行结果"),
):
    config = load_expression(regexp_yaml_file)
    with open(file, "r") as fd:
        multi_line, counter = split_text(fd, config.expressions)

    report(counter, config.expressions, result=multi_line)

    if sum(not i[1] for i in multi_line):
        if not no_multi and typer.confirm("是否查看未过滤多行结果", default=True):
            sep = f"\n\n{'-'*16}endline{'-'*16}\n\n"
            typer.echo_via_pager([i[0] + sep for i in multi_line if not i[1]])
    else:
        typer.echo("All Clear!!🎉")


if __name__ == "__main__":
    app()
