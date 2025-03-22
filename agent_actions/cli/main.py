"""
Main CLI entry point for the Agent Actions framework.
"""

import click

from agent_actions.cli.commands.init_command import init
from agent_actions.cli.commands.docs_command import docs
from agent_actions.cli.commands.run_command import run
from agent_actions.cli.commands.clean_command import clean
from agent_actions.cli.commands.render_command import render


@click.group()
def main() -> None:
    """Agent Actions CLI Tool - Framework for constructing and running agent workflows."""
    pass


main.add_command(init)
main.add_command(docs)
main.add_command(run)
main.add_command(clean)
main.add_command(render)


if __name__ == "__main__":
    main()
