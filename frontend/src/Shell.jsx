import { useSyncExternalStore } from 'react';
import { session } from './lib/http.js';
import { CatalogProvider } from './lib/catalog.jsx';
import { Link, match, usePath } from './lib/nav.jsx';
import Door from './screens/Door.jsx';
import Shopfront, { Wave } from './screens/Shopfront.jsx';
import Booth from './screens/Booth.jsx';
import Ledger from './screens/Ledger.jsx';
import Workbench from './screens/Workbench.jsx';

const useUser = () => useSyncExternalStore((cb) => session.subscribe(cb), () => session.user);

function screenFor(path, user) {
  let params;
  if ((params = match('/booth/:id', path))) return <Booth key={params.id} loungeId={params.id} user={user} />;
  if ((params = match('/ledger/:id', path))) return <Ledger loungeId={params.id} />;
  if (match('/workbench', path) && user.role === 'admin') return <Workbench />;
  return <Shopfront user={user} />;
}

export default function Shell() {
  const user = useUser();
  const path = usePath();
  if (!user) return <Door />;

  return (
    <CatalogProvider userKey={user.userId}>
      <nav className="shop-sign">
        <Link to="/" className="wordmark"><Wave size={30} /> The Listening Room</Link>
        <div className="sign-links">
          <Link to="/" className={path === '/' ? 'here' : ''}>Shopfront</Link>
          {user.role === 'admin' && <Link to="/workbench" className={path === '/workbench' ? 'here' : ''}>Workbench</Link>}
        </div>
        <div className="member">
          <span className="role-pill">{user.role.replace('_', '-')}</span>
          <span className="member-name">{user.displayName}</span>
          <button className="sign-out" onClick={() => session.signOut()}>sign out <span aria-hidden="true">→</span></button>
        </div>
      </nav>
      <main className="floor">{screenFor(path, user)}</main>
    </CatalogProvider>
  );
}
