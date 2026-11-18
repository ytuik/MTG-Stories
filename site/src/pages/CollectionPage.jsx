import { Link, useParams } from "react-router-dom";

export default function CollectionPage({ collections }) {
  // For the route "/collection/:slug", useParams() returns { slug: "bloomburrow" }.
  const { slug } = useParams();
  const collection = collections.find((item) => item.slug === slug);

  if (!collection) {
    return (
      <div>
        <p>Collection not found.</p>
        <Link to="/" className="text-amber-400 hover:underline">
          Back to all collections
        </Link>
      </div>
    );
  }

  return (
    <div>
      <Link to="/" className="text-sm text-amber-400 hover:underline">
        ← All collections
      </Link>
      <h1 className="mt-4 text-3xl font-bold">{collection.name}</h1>
      <p className="mt-1 text-slate-400">{collection.stories.length} stories</p>

      <ol className="mt-6 divide-y divide-slate-700 rounded-lg border border-slate-700 bg-slate-800">
        {collection.stories.map((story) => (
          <li key={story.file} className="flex gap-4 px-4 py-3">
            <span className="w-8 shrink-0 text-right text-slate-500">
              {story.order}
            </span>
            <span>{story.title}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}