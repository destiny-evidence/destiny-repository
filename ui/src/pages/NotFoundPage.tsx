// Fallback for unknown paths. Front Door serves index.html for every
// extensionless path, so the app has to say "not found" itself.

export default function NotFoundPage(_props: { default?: boolean }) {
  return (
    <div class="empty-state">
      <h3>Page not found</h3>
      <p>
        Return to the <a href="/">home page</a>.
      </p>
    </div>
  );
}
