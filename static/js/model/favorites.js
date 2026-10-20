// Leaf module: models.js and modelPicker.js both import it, and models.js
// already sits in an import cycle with modelPicker.js through sessions.js.
import Storage from '../storage.js';

const FAVORITES_KEY = 'odysseus-model-favorites';

export function loadFavorites() {
  return Storage.getJSON(FAVORITES_KEY, []);
}

export function toggleFavorite(mid) {
  const favs = loadFavorites();
  const idx = favs.indexOf(mid);
  if (idx >= 0) favs.splice(idx, 1);
  else favs.push(mid);
  Storage.setJSON(FAVORITES_KEY, favs);
  return idx < 0; // true when now favorited
}
