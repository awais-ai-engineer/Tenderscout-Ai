"use client";
export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <section className="empty" role="alert">
      <h1>This view could not load</h1>
      <p>Your request could not be completed. Please try again.</p>
      <button onClick={reset}>Try again</button>
    </section>
  );
}
