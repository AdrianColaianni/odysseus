// Versioned entry point: importers cache-bust through this file's ?v= query,
// while emailLibrary/index.js stays one module instance shared with its siblings.

export {
  refreshEmailLibrary,
  prewarmEmailLibrary,
  prewarmUnreadEmails,
  initEmailLibrary,
  isOpen,
  openEmailLibrary,
  openEmailFromTool,
  mountEmailSettings,
  openEmailLibrarySettings,
  closeEmailLibrary,
} from './emailLibrary/index.js';
