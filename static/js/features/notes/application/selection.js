/** Selected-note attachment retains synchronous acceptance; bulk requests report partial failure. */
async function countFailures(requests) {
  return (await Promise.allSettled(requests)).filter(result => result.status === 'rejected').length;
}

function summary(verb, total, failed) {
  return failed ? `${verb} ${total - failed}, ${failed} failed` : `${verb} ${total}`;
}

export function createSelectionOperations({
  app,
  api,
  effects,
  sendContext,
  exitSelection,
  fetchNotes
}) {
    const state = app.state;
    function attachSelected() {
      const ids = [...state.selectedIds];
      if (!ids.length) return;
      const detail = { noteIds: ids, accepted: false };
      sendContext(detail);
      if (!detail.accepted) {
        effects.showToast('Choose a chat or model before attaching notes');
        return;
      }
      exitSelection();
    }
    async function archiveSelected() {
      const ids = [...state.selectedIds];
      if (!ids.length) return;
      const failed = await countFailures(ids.map(id => api.patchNote(id, { archived: true })));
      exitSelection(); await fetchNotes(); effects.render(); effects.showToast(summary('Archived', ids.length, failed));
    }
    async function deleteSelected() {
      const ids = [...state.selectedIds];
      if (!ids.length) return;
      const ok = await effects.styledConfirm(`Delete ${ids.length} note${ids.length === 1 ? '' : 's'}?`, { confirmText: 'Delete', danger: true });
      if (!ok) return;
      const failed = await countFailures(ids.map(id => api.deleteNote(id)));
      exitSelection(); await fetchNotes(); effects.render(); effects.showToast(summary('Deleted', ids.length, failed));
    }
    return { attachSelected, archiveSelected, deleteSelected };
}
