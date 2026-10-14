const list = document.getElementById("task-list");
const form = document.getElementById("task-form");
const status = document.getElementById("status");
const instanceLabel = document.getElementById("instance");

function render(tasks) {
  list.innerHTML = "";
  for (const task of tasks) {
    const li = document.createElement("li");
    const span = document.createElement("span");
    span.textContent = task.text;
    const time = document.createElement("small");
    time.textContent = task.created_at.replace("T", " ");
    li.append(span, time);
    list.appendChild(li);
  }
}

async function loadTasks() {
  status.textContent = "Загружаю…";
  try {
    const response = await fetch("/api/tasks");
    if (!response.ok) throw new Error("HTTP " + response.status);
    const data = await response.json();
    render(data.tasks);
    instanceLabel.textContent = data.instance;
    status.textContent = "Сохранено записей: " + data.tasks.length;
  } catch (error) {
    status.textContent = "Не удалось загрузить задачи: " + error.message;
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = document.getElementById("task-input");
  const text = input.value.trim();
  if (!text) return;
  status.textContent = "Сохраняю…";
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error("HTTP " + response.status);
    input.value = "";
    await loadTasks();
  } catch (error) {
    status.textContent = "Не удалось сохранить: " + error.message;
  }
});

loadTasks();
