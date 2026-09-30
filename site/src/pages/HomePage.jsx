import { useState } from "react";
import CollectionCard from "../components/CollectionCard";

export default function HomePage({ collections }) {
  const [query, setQuery] = useState("");

  const normalizedQuery = query.trim().toLowerCase();
  const visibleCollections = collections.filter((collection) =>
    collection.name.toLowerCase().includes(normalizedQuery)
  );

  return (
    <div>
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search collections..."
        className="w-full rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 outline-none focus:border-amber-400"
      />

      <ul className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {visibleCollections.map((collection) => (
          <CollectionCard key={collection.slug} collection={collection} />
        ))}
      </ul>
    </div>
  );
}