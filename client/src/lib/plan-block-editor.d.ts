/** Types for the block editor carried over from the previous frontend. */

export interface BlockEditorOptions {
  initialMarkdown?: string;
  /** Return true when the Markdown was stored; the editor shows the outcome. */
  onSave?: (markdown: string) => Promise<boolean>;
  onChange?: (markdown: string) => void;
  onStatus?: (status: string) => void;
  saveDelay?: number;
}

export interface BlockEditor {
  getMarkdown(): string;
  hasUnsavedChanges(): boolean;
  destroy?(): void;
}

export function mount(container: HTMLElement, options?: BlockEditorOptions): BlockEditor;
export function parseMarkdown(markdown: string): unknown[];
export function serializeBlocks(blocks: unknown[]): string;
