import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import HomePage from "./pages/HomePage";
import CollectionPage from "./pages/CollectionPage";
import NotFoundPage from "./pages/NotFoundPage";

const RELEASES_URL = "https://github.com/polarkac/MTG-Stories/releases";

export default function App() {
  const [collections, setCollections] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}catalog.json`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((data) => setCollections(data.collections))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false)); // runs on success and on failure
  }, []);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <header className="border-b border-slate-800">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-4">
          <Link to="/" className="text-2xl font-bold hover:text-amber-400 text-center">
            MTG Stories
          </Link>
          {/* External links use a normal <a>; <Link> is only for pages of this site. */}
          <a
            href={RELEASES_URL}
            target="_blank"
            rel="noreferrer"
            className="text-sm text-amber-400 hover:underline"
          >
            Download PDFs/EPUBs
          </a>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        {loading && <p className="text-slate-400">Loading catalog...</p>}
        {error && (
          <p className="text-red-400">Could not load the catalog: {error}</p>
        )}
        {!loading && !error && (
          <Routes>
            <Route path="/" element={<HomePage collections={collections} />} />
            <Route
              path="/collection/:slug"
              element={<CollectionPage collections={collections} />}
            />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        )}
      </main>
    </div>
  );
}