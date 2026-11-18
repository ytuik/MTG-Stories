import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block text-amber-400 hover:underline">
        Go back home
      </Link>
    </div>
  );
}