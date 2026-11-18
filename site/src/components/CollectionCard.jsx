import { Link } from "react-router-dom";

export default function CollectionCard({ collection }) {
  return (
    <li>
      <Link
        to={`/collection/${collection.slug}`}
        className="block h-full rounded-lg border border-slate-700 bg-slate-800 p-4 shadow transition hover:border-amber-400"
      >
        <h2 className="text-lg font-semibold text-slate-100">
          {collection.name}
        </h2>
        <p className="mt-2 text-sm text-slate-400">
          {collection.stories.length} stories
        </p>
      </Link>
    </li>
  );
}