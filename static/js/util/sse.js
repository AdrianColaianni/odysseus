// Yields the payload of each `data: ` line in an SSE response body, holding
// back a line split across chunks until its newline arrives.
export async function* readSseData(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) return;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines) {
      if (line.startsWith('data: ')) yield line.slice(6);
    }
  }
}
