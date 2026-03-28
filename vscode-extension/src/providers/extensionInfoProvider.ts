/**
 * Extension Info Tree View Provider
 *
 * Displays extension version, LSP server status, and current configuration
 * in the Agent Actions sidebar panel.
 */

import * as vscode from 'vscode';
import { LanguageClient, State } from 'vscode-languageclient/node';

type InfoNode = SectionNode | InfoItemNode;

class SectionNode extends vscode.TreeItem {
    constructor(
        public readonly label: string,
        public readonly section: 'about' | 'configuration',
    ) {
        super(label, vscode.TreeItemCollapsibleState.Collapsed);
        this.contextValue = 'agentActions.infoSection';
        this.iconPath = section === 'about'
            ? new vscode.ThemeIcon('info')
            : new vscode.ThemeIcon('settings-gear');
    }
}

class InfoItemNode extends vscode.TreeItem {
    constructor(
        label: string,
        description: string,
        options?: { icon?: vscode.ThemeIcon; command?: vscode.Command },
    ) {
        super(label, vscode.TreeItemCollapsibleState.None);
        this.description = description;
        if (options?.icon) this.iconPath = options.icon;
        if (options?.command) this.command = options.command;
    }
}

export class ExtensionInfoProvider implements vscode.TreeDataProvider<InfoNode>, vscode.Disposable {
    private readonly _onDidChangeTreeData = new vscode.EventEmitter<InfoNode | undefined>();
    readonly onDidChangeTreeData = this._onDidChangeTreeData.event;
    private readonly disposables: vscode.Disposable[] = [];

    constructor(
        private readonly getClient: () => LanguageClient | undefined,
        private readonly extensionContext: vscode.ExtensionContext,
    ) {
        this.disposables.push(
            vscode.workspace.onDidChangeConfiguration((e) => {
                if (e.affectsConfiguration('agentActions')) {
                    this._onDidChangeTreeData.fire(undefined);
                }
            }),
        );
    }

    dispose(): void {
        this._onDidChangeTreeData.dispose();
        for (const d of this.disposables) d.dispose();
    }

    refresh(): void {
        this._onDidChangeTreeData.fire(undefined);
    }

    getTreeItem(element: InfoNode): vscode.TreeItem {
        return element;
    }

    getChildren(element?: InfoNode): InfoNode[] {
        if (!element) {
            return [
                new SectionNode('About', 'about'),
                new SectionNode('Configuration', 'configuration'),
            ];
        }

        if (element instanceof SectionNode) {
            return element.section === 'about'
                ? this.getAboutItems()
                : this.getConfigItems();
        }

        return [];
    }

    private getAboutItems(): InfoItemNode[] {
        const ext = this.extensionContext.extension;
        const version = ext?.packageJSON?.version ?? 'unknown';

        const currentClient = this.getClient();
        let lspStatus: string;
        let lspIcon: vscode.ThemeIcon;

        if (!currentClient) {
            lspStatus = 'Stopped';
            lspIcon = new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('charts.red'));
        } else {
            switch (currentClient.state) {
                case State.Running:
                    lspStatus = 'Running';
                    lspIcon = new vscode.ThemeIcon('check', new vscode.ThemeColor('charts.green'));
                    break;
                case State.Starting:
                    lspStatus = 'Starting';
                    lspIcon = new vscode.ThemeIcon('sync~spin', new vscode.ThemeColor('charts.yellow'));
                    break;
                default:
                    lspStatus = 'Stopped';
                    lspIcon = new vscode.ThemeIcon('circle-slash', new vscode.ThemeColor('charts.red'));
                    break;
            }
        }

        return [
            new InfoItemNode('Version', `v${version}`, { icon: new vscode.ThemeIcon('tag') }),
            new InfoItemNode('LSP Server', lspStatus, { icon: lspIcon }),
        ];
    }

    private getConfigItems(): InfoItemNode[] {
        const config = vscode.workspace.getConfiguration('agentActions');
        const openSetting = (key: string): vscode.Command => ({
            command: 'workbench.action.openSettings',
            title: 'Open Setting',
            arguments: [`agentActions.${key}`],
        });

        const interpreter = config.get<string[]>('interpreter') ?? [];
        const interpreterDisplay = interpreter.length > 0 ? interpreter[0] : 'auto-detect';
        const serverPath = config.get<string>('serverPath') || 'agac-lsp';

        return [
            new InfoItemNode('Interpreter', interpreterDisplay, {
                icon: new vscode.ThemeIcon('symbol-misc'),
                command: openSetting('interpreter'),
            }),
            new InfoItemNode('Server Path', serverPath, {
                icon: new vscode.ThemeIcon('terminal'),
                command: openSetting('serverPath'),
            }),
        ];
    }
}
