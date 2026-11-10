// JsonDisplay component for displaying JSON content with copy functionality

interface JsonDisplayProps {
  data: any;
  title?: string;
  showCopyButton?: boolean;
  maxHeight?: string;
  className?: string;
}

export default function JsonDisplay({
  data,
  title,
  showCopyButton = false,
  className = "",
}: JsonDisplayProps) {
  function handleCopy() {
    navigator.clipboard.writeText(JSON.stringify(data, null, 2));
  }

  return (
    <div class={`json-display ${className}`}>
      {(title || showCopyButton) && (
        <div class="json-display-header">
          <span class="json-display-title">{title}</span>
          {showCopyButton && (
            <button
              class="json-display-copy-btn"
              onClick={handleCopy}
              title="Copy JSON to clipboard"
            >
              Copy
            </button>
          )}
        </div>
      )}
      <pre class="json-display-content">{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}
