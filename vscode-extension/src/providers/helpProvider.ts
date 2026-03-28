/**
 * Help Tree View Provider
 *
 * Displays help links and resources in the Agent Actions sidebar panel.
 */

import * as vscode from 'vscode';

class HelpItemNode extends vscode.TreeItem {
    constructor(
        label: string,
        icon: vscode.ThemeIcon,
        command: vscode.Command,
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.iconPath = icon;
        this.command = command;
    }
}

export class HelpProvider implements vscode.TreeDataProvider<HelpItemNode> {
    getTreeItem(element: HelpItemNode): vscode.TreeItem {
        return element;
    }

    getChildren(): HelpItemNode[] {
        return [
            new HelpItemNode(
                'Documentation',
                new vscode.ThemeIcon('book'),
                {
                    command: 'agentActions.openDocs',
                    title: 'Open Documentation',
                },
            ),
            new HelpItemNode(
                'Get Support',
                new vscode.ThemeIcon('comment-discussion'),
                {
                    command: 'vscode.open',
                    title: 'Get Support',
                    arguments: [vscode.Uri.parse('https://github.com/Muizzkolapo/agent-actions/discussions')],
                },
            ),
            new HelpItemNode(
                'Report a Bug',
                new vscode.ThemeIcon('bug'),
                {
                    command: 'vscode.open',
                    title: 'Report a Bug',
                    arguments: [vscode.Uri.parse('https://github.com/Muizzkolapo/agent-actions/issues/new')],
                },
            ),
            new HelpItemNode(
                'Show Output Logs',
                new vscode.ThemeIcon('output'),
                {
                    command: 'workbench.action.output.show',
                    title: 'Show Output Logs',
                },
            ),
        ];
    }
}
