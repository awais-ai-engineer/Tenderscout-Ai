export function BrandLogo() {
  return (
    <div className="brand-logo">
      <svg
        className="brand-logo-mark"
        viewBox="0 0 42 42"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M8 8.5L29.5 5L23 18.5L8 8.5Z"
          fill="#8B7CF6"
        />

        <path
          d="M8 8.5L23 18.5L12.5 29L5 20L8 8.5Z"
          fill="#725EE8"
        />

        <path
          d="M23 18.5L34.5 24L21 37L12.5 29L23 18.5Z"
          fill="#5943C9"
        />

        <path
          d="M29.5 5L34.5 24L23 18.5L29.5 5Z"
          fill="#9B8CFF"
        />
      </svg>

      <div className="brand-logo-copy">
        <strong>TenderScout</strong>
      </div>
    </div>
  );
}