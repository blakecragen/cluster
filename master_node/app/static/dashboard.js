/* ================================
      JOB MANAGEMENT
================================ */

function deleteJob(jobId) {
  if (confirm("Delete job " + jobId + "?")) {
    fetch(`/delete_job/${jobId}`, { method: "POST" })
      .then(r => r.json())
      .then(data => {
        alert(data.message || "Job deleted");
        location.reload();
      });
  }
}

function downloadResult(jobId) {
  window.location.href = `/download_result/${jobId}`;
  fetch(`/mark_collected/${jobId}`, { method: "POST" });

  setTimeout(() => location.reload(), 2000);
}

function toggleSelectAll() {
  const checked = document.getElementById("selectAll").checked;
  document.querySelectorAll(".job-select")
    .forEach(cb => cb.checked = checked);
}

function deleteSelected() {
  const selected = Array.from(document.querySelectorAll(".job-select:checked"))
                        .map(cb => cb.value);

  if (selected.length === 0) {
    alert("No jobs selected.");
    return;
  }

  if (!confirm(`Delete ${selected.length} selected job(s)?`)) return;

  Promise.all(
    selected.map(id => fetch(`/delete_job/${id}`, { method: "POST" }))
  ).then(() => {
    alert("Selected jobs deleted.");
    location.reload();
  });
}

function copyText(id) {
  navigator.clipboard.writeText(document.getElementById(id).innerText)
    .then(() => alert("Copied!"));
}


/* ================================
       LOAD KUBERNETES NODES
================================ */

async function loadNodes() {
  try {
    const res = await fetch("/nodes");
    const nodes = await res.json();

    const tbody = document.querySelector("#nodesTable tbody");
    tbody.innerHTML = "";

    if (!nodes || nodes.length === 0) {
      tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;">No nodes found</td></tr>`;
      return;
    }

    nodes.forEach(n => {
      tbody.innerHTML += `
        <tr>
          <td>${n.name}</td>
          <td class="${n.status === 'Ready' ? 'status-ready' : 'status-notready'}">${n.status}</td>
          <td>${n.role}</td>
          <td>${n.arch}</td>
          <td>${n.cpu}</td>
          <td>${n.os_image}</td>
          <td>${n.kernel}</td>
          <td>${n.internal_ip}</td>
          <td>${n.heartbeat}</td>
        </tr>`;
    });

  } catch (e) {
    console.error("Failed to load nodes:", e);
  }
}


/* ================================
       LOAD CROSS-OS WORKERS
================================ */

async function loadWorkers() {
  try {
    const res = await fetch("/workers");
    const workers = await res.json();

    const tbody = document.querySelector("#workersTable tbody");
    tbody.innerHTML = "";

    if (!workers || workers.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;">No workers connected</td></tr>`;
      return;
    }

    workers.forEach(w => {
      tbody.innerHTML += `
        <tr>
          <td>${w.hostname}</td>
          <td>${w.status}</td>
          <td>${w.os}</td>
          <td>${w.cpu}</td>
          <td>${w.kernel}</td>
          <td>${w.ip}</td>
          <td>${w.last_heartbeat}</td>
        </tr>`;
    });

  } catch (e) {
    console.error("Failed to load workers:", e);
  }
}


/* ================================
          AUTO REFRESH
================================ */

loadNodes();
setInterval(loadNodes, 20000);   // 20 sec refresh

loadWorkers();
setInterval(loadWorkers, 2000);  // 2 sec refresh
setTimeout(() => location.reload(), 5000);