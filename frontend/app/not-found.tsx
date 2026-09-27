import Link from "next/link";
export default function NotFound() {
  return (
    <section className="empty">
      <h1>Record not found</h1>
      <p>This record or page is unavailable.</p>
      <Link className="button" href="/discover">
        Discover opportunities
      </Link>
    </section>
  );
}
