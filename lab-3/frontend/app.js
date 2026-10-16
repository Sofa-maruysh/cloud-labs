const status = document.querySelector('#status');
const tasks = document.querySelector('#tasks');
const form = document.querySelector('#task-form');

async function loadTasks() {
  const response = await fetch('/api/tasks');
  if (!response.ok) throw new Error('База временно недоступна. Попробуйте ещё раз.');
  const data = await response.json();
  tasks.replaceChildren(...data.map(task => {
    const item = document.createElement('li');
    item.textContent = task.text;
    return item;
  }));
  status.textContent = data.length ? '' : 'Пока задач нет.';
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const response = await fetch('/api/tasks', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: form.elements.text.value}),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || 'Не удалось сохранить задачу.');
    }
    form.reset();
    await loadTasks();
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

loadTasks().catch(error => { status.textContent = error.message; });
