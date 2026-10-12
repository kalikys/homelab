import { Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Project from "./pages/Project";
import ItemPage from "./pages/Item";
import Waits from "./pages/Waits";
import Sessions from "./pages/Sessions";
import SessionPage from "./pages/Session";

export default function App() {
  return (
    <div className="mx-auto max-w-5xl px-4 pb-16">
      <header className="flex items-center justify-between py-5">
        <Link to="/" className="text-lg font-semibold">Проекты</Link>
        <nav className="flex gap-4 text-sm text-muted">
          <Link to="/waits" className="hover:text-fg">Ждёт тебя</Link>
          <Link to="/sessions" className="hover:text-fg">Неразобранные</Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/p/:slug" element={<Project />} />
        <Route path="/i/:id" element={<ItemPage />} />
        <Route path="/s/:id" element={<SessionPage />} />
        <Route path="/waits" element={<Waits />} />
        <Route path="/sessions" element={<Sessions />} />
      </Routes>
    </div>
  );
}
