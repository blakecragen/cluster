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
  // Trigger file download
  window.location.href = `/download_result/${jobId}`;
  // Mark collected
  fetch(`/mark_collected/${jobId}`, { method: "POST" });
  // Refresh
  setTimeout(() => location.reload(), 3000);
}

function toggleSelectAll() {
  const selectAll = document.getElementById("selectAll").checked;
  document.querySelectorAll(".job-select").forEach(cb => cb.checked = selectAll);
}

function deleteSelected() {
  const selected = Array.from(document.querySelectorAll(".job-select:checked"))
                        .map(cb => cb.value);
  if (selected.length === 0) {
    alert("No jobs selected.");
    return;
  }

  if (!confirm(`Delete ${selected.length} selected job(s)?`)) return;

  Promise.all(selected.map(id =>
    fetch(`/delete_job/${id}`, { method: "POST" })
      .then(r => r.json())
  )).then(() => {
    alert("Selected jobs deleted.");
    location.reload();
  });
}

setTimeout(() => location.reload(), 5000); // auto-refresh
