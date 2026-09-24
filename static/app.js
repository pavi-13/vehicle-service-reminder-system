// ============================================================
// VehicleCare Frontend
// ============================================================

const API = "/api";

let token = localStorage.getItem("vehiclecare_token");
let currentUser = null;
let currentPage = "dashboard";
let pollingTimer = null;

// ============================================================
// INIT
// ============================================================

document.addEventListener("DOMContentLoaded", async () => {
  document.getElementById("intakeCheckIn").value =
    new Date().toISOString().slice(0, 10);

  if (token) {
    try {
      currentUser = await api("/me");
      showMainApp();
      await loadDashboard();
      startPolling();
    } catch (error) {
      logout(false);
    }
  }
});

// ============================================================
// API
// ============================================================

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {})
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(API + path, {
    ...options,
    headers
  });

  let data = null;

  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    throw new Error(
      data.detail ||
      data.message ||
      "Something went wrong"
    );
  }

  return data;
}

// ============================================================
// AUTH UI
// ============================================================

function showAuth(type) {
  const loginForm = document.getElementById("loginForm");
  const registerForm = document.getElementById("registerForm");
  const loginTab = document.getElementById("loginTab");
  const registerTab = document.getElementById("registerTab");

  if (type === "login") {
    loginForm.classList.remove("hidden");
    registerForm.classList.add("hidden");
    loginTab.classList.add("active");
    registerTab.classList.remove("active");
  } else {
    loginForm.classList.add("hidden");
    registerForm.classList.remove("hidden");
    loginTab.classList.remove("active");
    registerTab.classList.add("active");
  }
}

// ============================================================
// REGISTER
// ============================================================

async function register(event) {
  event.preventDefault();

  const message = document.getElementById("registerMessage");
  message.textContent = "Creating account...";

  try {
    const data = await api("/auth/register", {
      method: "POST",
      body: JSON.stringify({
        name: document.getElementById("registerName").value,
        email: document.getElementById("registerEmail").value || null,
        phone: document.getElementById("registerPhone").value || null,
        password: document.getElementById("registerPassword").value
      })
    });

    token = data.token;
    currentUser = data.user;
    localStorage.setItem("vehiclecare_token", token);

    showToast("Account created successfully");
    showMainApp();
    await loadDashboard();
    startPolling();
  } catch (error) {
    message.textContent = error.message;
  }
}

// ============================================================
// LOGIN
// ============================================================

async function login(event) {
  event.preventDefault();

  const message = document.getElementById("loginMessage");
  message.textContent = "Logging in...";

  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({
        identifier: document.getElementById("loginIdentifier").value,
        password: document.getElementById("loginPassword").value
      })
    });

    token = data.token;
    currentUser = data.user;
    localStorage.setItem("vehiclecare_token", token);

    message.textContent = "";
    showMainApp();
    await loadDashboard();
    startPolling();
  } catch (error) {
    message.textContent = error.message;
  }
}

// ============================================================
// LOGOUT
// ============================================================

function logout(showMessage = true) {
  token = null;
  currentUser = null;
  localStorage.removeItem("vehiclecare_token");

  if (pollingTimer) {
    clearInterval(pollingTimer);
  }

  document.getElementById("mainScreen").classList.add("hidden");
  document.getElementById("authScreen").classList.remove("hidden");

  if (showMessage) {
    showToast("Logged out");
  }
}

// ============================================================
// SHOW MAIN APP
// ============================================================

function showMainApp() {
  document.getElementById("authScreen").classList.add("hidden");
  document.getElementById("mainScreen").classList.remove("hidden");

  const name = currentUser?.name || "User";

  document.getElementById("sidebarUserName").textContent = name;
  document.getElementById("topUserName").textContent = name;
  document.getElementById("userAvatar").textContent =
    name.charAt(0).toUpperCase();
  document.getElementById("topAvatar").textContent =
    name.charAt(0).toUpperCase();

  const role =
    currentUser?.role === "admin"
      ? "Administrator"
      : "Customer";

  document.getElementById("sidebarUserRole").textContent = role;

  if (currentUser?.role === "admin") {
    document.getElementById("adminServiceNav").classList.remove("hidden");
    document.getElementById("adminFeedbackNav").classList.remove("hidden");
  }
}

// ============================================================
// NAVIGATION
// ============================================================

async function navigate(page) {
  currentPage = page;

  document.querySelectorAll(".page").forEach(el => {
    el.classList.add("hidden");
  });

  const target = document.getElementById(`page-${page}`);

  if (target) {
    target.classList.remove("hidden");
  }

  document.querySelectorAll(".nav-item").forEach(button => {
    button.classList.toggle("active", button.dataset.page === page);
  });

  const titles = {
    dashboard: [
      "Dashboard",
      "Overview of your vehicle service"
    ],
    vehicles: [
      "My Vehicles",
      "Manage your registered vehicles"
    ],
    services: [
      "My Service",
      "Track your service progress"
    ],
    notifications: [
      "Notifications",
      "Service updates and reminders"
    ],
    admin: [
      "Service Desk",
      "Vehicle intake and service management"
    ],
    feedback: [
      "Customer Feedback",
      "Service ratings and comments"
    ]
  };

  const info = titles[page] || titles.dashboard;

  document.getElementById("pageTitle").textContent = info[0];
  document.getElementById("pageSubtitle").textContent = info[1];

  try {
    if (page === "dashboard") {
      await loadDashboard();
    }

    if (page === "vehicles") {
      await loadVehicles();
    }

    if (page === "services") {
      await loadServices();
    }

    if (page === "notifications") {
      await loadNotifications();
    }

    if (page === "admin") {
      await loadAdminJobs();
    }

    if (page === "feedback") {
      await loadFeedback();
    }
  } catch (error) {
    showToast(error.message, "error");
  }
}

// ============================================================
// DASHBOARD
// ============================================================

async function loadDashboard() {
  const data = await api("/dashboard");
  renderDashboardStats(data);

  const jobs = await api("/jobs");
  renderDashboardJobs(
    Array.isArray(jobs)
      ? jobs.slice(0, 6)
      : []
  );
}

// ============================================================
// DASHBOARD STATS
// ============================================================

function renderDashboardStats(data) {
  const container = document.getElementById("dashboardStats");

  container.innerHTML = `
    <div class="stat-card">
      <div class="stat-icon">🚗</div>
      <div>
        <span>Vehicles</span>
        <strong>${data.vehicles || 0}</strong>
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-icon">🔧</div>
      <div>
        <span>Active Services</span>
        <strong>${data.active_jobs || 0}</strong>
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-icon">✓</div>
      <div>
        <span>Completed</span>
        <strong>${data.completed_jobs || 0}</strong>
      </div>
    </div>

    <div class="stat-card">
      <div class="stat-icon">⏰</div>
      <div>
        <span>Due Services</span>
        <strong>${data.due_services || 0}</strong>
      </div>
    </div>
  `;
}

// ============================================================
// DASHBOARD JOBS
// ============================================================

function renderDashboardJobs(jobs) {
  const container = document.getElementById("dashboardJobs");

  if (!jobs.length) {
    container.innerHTML = emptyState(
      "No service history yet",
      "Your service activity will appear here."
    );
    return;
  }

  container.innerHTML = jobs.map(jobCard).join("");
}

// ============================================================
// VEHICLES
// ============================================================

async function loadVehicles() {
  const vehicles = await api("/vehicles");
  const container = document.getElementById("vehiclesGrid");

  if (!vehicles.length) {
    container.innerHTML = emptyState(
      "No vehicles added",
      "Add your vehicle to start tracking services."
    );
    return;
  }

  container.innerHTML = vehicles.map(vehicleCard).join("");
}

// ============================================================
// VEHICLE CARD
// ============================================================

function vehicleCard(vehicle) {
  const current = vehicle.current_job;
  const status = current?.status || "No active service";

  return `
    <div
      class="vehicle-card"
      onclick="openVehicleHistory(${vehicle.id})"
    >
      <div class="vehicle-card-top">
        <div class="vehicle-icon">🚗</div>

        <span class="status-pill ${
          current
            ? statusClass(status)
            : "neutral"
        }">
          ${escapeHtml(status)}
        </span>
      </div>

      <h3>
        ${escapeHtml(vehicle.brand)}
        ${escapeHtml(vehicle.model)}
      </h3>

      <div class="registration">
        ${escapeHtml(vehicle.registration_no)}
      </div>

      <div class="vehicle-meta">
        <span>${escapeHtml(vehicle.type || "Car")}</span>
        <span>${vehicle.year || "-"}</span>
      </div>

      <div class="vehicle-footer">
        <span>${vehicle.service_count || 0} service(s)</span>
        <span>View History →</span>
      </div>
    </div>
  `;
}

// ============================================================
// ADD VEHICLE MODAL
// ============================================================

function openVehicleModal() {
  document.getElementById("vehicleModal").classList.remove("hidden");
}

async function addVehicle(event) {
  event.preventDefault();

  try {
    await api("/vehicles", {
      method: "POST",
      body: JSON.stringify({
        type: document.getElementById("vehicleType").value,
        brand: document.getElementById("vehicleBrand").value,
        model: document.getElementById("vehicleModel").value,
        registration_no: document.getElementById("vehicleRegistration").value,
        year: numberOrNull(document.getElementById("vehicleYear").value),
        last_service_date: valueOrNull(
          document.getElementById("vehicleLastService").value
        ),
        next_service_date: valueOrNull(
          document.getElementById("vehicleNextService").value
        ),
        notes: valueOrNull(document.getElementById("vehicleNotes").value)
      })
    });

    closeModal("vehicleModal");
    showToast("Vehicle added successfully");
    event.target.reset();

    await loadVehicles();
    await loadDashboard();
  } catch (error) {
    showToast(error.message, "error");
  }
}

// ============================================================
// SERVICES
// ============================================================

async function loadServices() {
  const jobs = await api("/jobs");
  const container = document.getElementById("servicesGrid");

  if (!jobs.length) {
    container.innerHTML = emptyState(
      "No services yet",
      "Your service details will appear after vehicle intake."
    );
    return;
  }

  container.innerHTML = jobs.map(jobCard).join("");
}

// ============================================================
// JOB CARD
// ============================================================

function jobCard(job) {
  const status = job.status || "Received";
  const progress = serviceProgress(status);

  return `
    <div
      class="job-card service-clickable-card"
      onclick="openServiceDetails(${Number(job.id)})"
      style="cursor:pointer;"
    >
      <div class="job-card-header">
        <div>
          <span class="job-service-type">
            ${escapeHtml(job.service_type || "Service")}
          </span>

          <h3>
            ${escapeHtml(job.brand || "")}
            ${escapeHtml(job.model || "")}
          </h3>

          <div class="registration">
            ${escapeHtml(job.registration_no || "")}
          </div>
        </div>

        <span class="status-pill ${statusClass(status)}">
          ${escapeHtml(status)}
        </span>
      </div>

      <div class="job-info-grid">
        <div>
          <span>Token</span>
          <strong>${escapeHtml(job.token_number || "-")}</strong>
        </div>

        <div>
          <span>Check-in</span>
          <strong>${formatDate(job.check_in_date)}</strong>
        </div>

        <div>
          <span>Delivery</span>
          <strong>${formatDate(job.expected_delivery_date)}</strong>
        </div>

        <div>
          <span>Bill</span>
          <strong>₹${money(job.bill_amount)}</strong>
        </div>
      </div>

      <div class="progress-section">
        <div class="progress-header">
          <span>Service Progress</span>
          <strong>${progress}%</strong>
        </div>

        <div class="progress-bar">
          <div
            class="progress-fill"
            style="width:${progress}%"
          ></div>
        </div>
      </div>

      <div class="service-card-hint">
        Click to view service details →
      </div>

      ${
        status === "Completed"
          ? `
            <button
              type="button"
              class="feedback-action-btn"
              onclick="
                event.stopPropagation();
                openFeedbackForm(${Number(job.id)})
              "
            >
              ★ Give Feedback
            </button>
          `
          : ""
      }
    </div>
  `;
}

// ============================================================
// ADMIN VEHICLE SEARCH
// ============================================================

async function searchAdminVehicle() {
  const q = document.getElementById("adminVehicleSearch").value.trim();
  const container = document.getElementById("adminSearchResults");

  if (!q) {
    container.innerHTML = `
      <div class="info-message">
        Enter a registration number.
      </div>
    `;
    return;
  }

  container.innerHTML = `<div class="loading">Searching...</div>`;

  try {
    const vehicles = await api(
      `/admin/vehicle-search?q=${encodeURIComponent(q)}`
    );

    if (!vehicles.length) {
      container.innerHTML = emptyState(
        "Vehicle not found",
        "Make sure the vehicle is already registered under My Vehicles."
      );
      return;
    }

    container.innerHTML = vehicles.map(adminVehicleResult).join("");
  } catch (error) {
    container.innerHTML = `
      <div class="error-box">
        ${escapeHtml(error.message)}
      </div>
    `;
  }
}

// ============================================================
// ADMIN VEHICLE RESULT
// ============================================================

function adminVehicleResult(vehicle) {
  const active = vehicle.active_job;

  return `
    <div class="search-result-card">
      <div class="search-result-main">
        <div class="vehicle-icon">🚗</div>

        <div>
          <h3>
            ${escapeHtml(vehicle.brand)}
            ${escapeHtml(vehicle.model)}
          </h3>

          <strong class="registration">
            ${escapeHtml(vehicle.registration_no)}
          </strong>

          <p>
            Customer:
            ${escapeHtml(vehicle.owner_name || "Customer")}
          </p>
        </div>
      </div>

      <div class="search-result-actions">
        ${
          active
            ? `
              <span class="status-pill ${statusClass(active.status)}">
                ${escapeHtml(active.status)}
              </span>

              <button
                class="secondary-btn"
                onclick="openJobUpdate(${active.id})"
              >
                Update Service
              </button>
            `
            : `
              <button
                class="primary-btn"
                onclick="openServiceIntake(
                  ${vehicle.id},
                  '${escapeJs(vehicle.brand)} ${escapeJs(vehicle.model)}',
                  '${escapeJs(vehicle.registration_no)}'
                )"
              >
                Start Service Intake
              </button>
            `
        }
      </div>
    </div>
  `;
}

// ============================================================
// SERVICE INTAKE
// ============================================================

function openServiceIntake(vehicleId, vehicleName, registration) {
  document.getElementById("intakeVehicleId").value = vehicleId;

  document.getElementById("intakeVehicleTitle").textContent =
    `${vehicleName} • ${registration}`;

  document.getElementById("intakeCheckIn").value =
    new Date().toISOString().slice(0, 10);

  document.getElementById("serviceModal").classList.remove("hidden");
}

async function createService(event) {
  event.preventDefault();

  try {
    const data = await api("/jobs", {
      method: "POST",
      body: JSON.stringify({
        vehicle_id: Number(document.getElementById("intakeVehicleId").value),
        check_in_date: document.getElementById("intakeCheckIn").value,
        expected_delivery_date: valueOrNull(
          document.getElementById("intakeDelivery").value
        ),
        service_type: document.getElementById("intakeServiceType").value,
        complaint: valueOrNull(
          document.getElementById("intakeComplaint").value
        ),
        damage_details: valueOrNull(
          document.getElementById("intakeDamage").value
        ),
        insurance_details: valueOrNull(
          document.getElementById("intakeInsurance").value
        ),
        estimate_amount:
          Number(document.getElementById("intakeEstimate").value) || 0,
        odometer: numberOrNull(
          document.getElementById("intakeOdometer").value
        ),
        assigned_executive: valueOrNull(
          document.getElementById("intakeExecutive").value
        )
      })
    });

    // Service successfully created
    closeModal("serviceModal");

    if (event.target && typeof event.target.reset === "function") {
      event.target.reset();
    }

    showToast(
      `Service started successfully. Token: ${
        data.token_number ||
        data.job?.token_number ||
        "Generated"
      }`
    );

    // Refresh admin list.
    // If only refresh fails, do NOT show "Something went wrong".
    try {
      await loadAdminJobs();
    } catch (refreshError) {
      console.warn(
        "Service created successfully, but admin list refresh failed:",
        refreshError
      );
    }
  } catch (error) {
    showToast(
      error.message || "Unable to start service",
      "error"
    );
  }
}

// ============================================================
// ADMIN JOBS
// ============================================================

async function loadAdminJobs() {
  const jobs = await api("/jobs");
  const container = document.getElementById("adminJobsGrid");

  const activeJobs = jobs.filter(job => job.status !== "Completed");

  if (!activeJobs.length) {
    container.innerHTML = emptyState(
      "No active services",
      "Search a vehicle above to start a service intake."
    );
    return;
  }

  container.innerHTML = activeJobs.map(adminJobCard).join("");
}

// ============================================================
// ADMIN JOB CARD
// ============================================================

function adminJobCard(job) {
  return `
    <div class="job-card admin-job-card">
      <div class="job-card-header">
        <div>
          <span class="job-service-type">
            ${escapeHtml(job.service_type || "Service")}
          </span>

          <h3>
            ${escapeHtml(job.brand || "")}
            ${escapeHtml(job.model || "")}
          </h3>

          <div class="registration">
            ${escapeHtml(job.registration_no || "")}
          </div>
        </div>

        <span class="status-pill ${statusClass(job.status)}">
          ${escapeHtml(job.status)}
        </span>
      </div>

      <div class="admin-job-details">
        <div>
          <span>Token</span>
          <strong>${escapeHtml(job.token_number || "-")}</strong>
        </div>

        <div>
          <span>Customer</span>
          <strong>${escapeHtml(job.owner_name || "Customer")}</strong>
        </div>

        <div>
          <span>Executive</span>
          <strong>${escapeHtml(job.assigned_executive || "-")}</strong>
        </div>

        <div>
          <span>Estimate</span>
          <strong>₹${money(job.estimate_amount)}</strong>
        </div>
      </div>

      <button
        class="primary-btn full"
        onclick="openJobUpdate(${job.id})"
      >
        Update Service
      </button>
    </div>
  `;
}

// ============================================================
// JOB UPDATE
// ============================================================

async function openJobUpdate(jobId) {
  try {
    // Get all admin jobs
    // because GET /jobs/{jobId} is not available.
    const jobs = await api("/jobs");

    const job = Array.isArray(jobs)
      ? jobs.find(item => Number(item.id) === Number(jobId))
      : null;

    if (!job) {
      throw new Error("Service job not found");
    }

    document.getElementById("jobUpdateId").value = job.id;

    document.getElementById("jobModalVehicle").textContent =
      `${job.brand || ""} ${job.model || ""} • ${job.registration_no || ""}`;

    document.getElementById("jobStatus").value =
      job.status || "Received";

    document.getElementById("jobBill").value =
      job.bill_amount ?? 0;

    document.getElementById("jobPaymentMethod").value =
      job.payment_method || "Pending";

    document.getElementById("jobPaymentStatus").value =
      job.payment_status || "Pending";

    document.getElementById("jobNextService").value =
      job.next_service_date || "";

    document.getElementById("jobWorkDone").value =
      job.work_done || "";

    document.getElementById("jobTechnicianNotes").value =
      job.technician_notes || "";

    document.getElementById("jobModal").classList.remove("hidden");
  } catch (error) {
    showToast(
      error.message || "Unable to open service update",
      "error"
    );
  }
}

async function updateJob(event) {
  event.preventDefault();

  const jobId = document.getElementById("jobUpdateId").value;

  try {
    await api(`/jobs/${jobId}`, {
      method: "PATCH",
      body: JSON.stringify({
        status: document.getElementById("jobStatus").value,
        bill_amount:
          Number(document.getElementById("jobBill").value) || 0,
        payment_method: document.getElementById("jobPaymentMethod").value,
        payment_status: document.getElementById("jobPaymentStatus").value,
        next_service_date: valueOrNull(
          document.getElementById("jobNextService").value
        ),
        work_done: valueOrNull(
          document.getElementById("jobWorkDone").value
        ),
        technician_notes: valueOrNull(
          document.getElementById("jobTechnicianNotes").value
        )
      })
    });

    closeModal("jobModal");
    showToast("Service updated successfully");
    await loadAdminJobs();
  } catch (error) {
    showToast(error.message, "error");
  }
}

// ============================================================
// VEHICLE HISTORY
// ============================================================

async function openVehicleHistory(vehicleId) {
  try {
    const data = await api(`/vehicles/${vehicleId}`);
    const vehicle = data.vehicle;

    document.getElementById("historyVehicleTitle").textContent =
      `${vehicle.brand} ${vehicle.model} • ${vehicle.registration_no}`;

    const history = data.history || [];
    const container = document.getElementById("historyContent");

    if (!history.length) {
      container.innerHTML = emptyState(
        "No service history",
        "This vehicle has not completed any service yet."
      );
    } else {
      container.innerHTML = history.map(historyItem).join("");
    }

    document.getElementById("historyModal").classList.remove("hidden");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function historyItem(job) {
  return `
    <div class="history-item">
      <div class="history-item-header">
        <div>
          <span class="job-service-type">
            ${escapeHtml(job.service_type || "Service")}
          </span>

          <h3>${escapeHtml(job.token_number || "-")}</h3>
        </div>

        <span class="status-pill ${statusClass(job.status)}">
          ${escapeHtml(job.status)}
        </span>
      </div>

      <div class="history-grid">
        <div>
          <span>Date</span>
          <strong>${formatDate(job.check_in_date)}</strong>
        </div>

        <div>
          <span>Bill</span>
          <strong>₹${money(job.bill_amount)}</strong>
        </div>

        <div>
          <span>Payment</span>
          <strong>${escapeHtml(job.payment_status || "Pending")}</strong>
        </div>

        <div>
          <span>Next Service</span>
          <strong>${formatDate(job.next_service_date)}</strong>
        </div>
      </div>

      ${
        job.complaint
          ? `
            <div class="history-note">
              <strong>Complaint</strong>
              <p>${escapeHtml(job.complaint)}</p>
            </div>
          `
          : ""
      }

      ${
        job.work_done
          ? `
            <div class="history-note">
              <strong>Work Done</strong>
              <p>${escapeHtml(job.work_done)}</p>
            </div>
          `
          : ""
      }
    </div>
  `;
}

// ============================================================
// NOTIFICATIONS
// ============================================================

async function loadNotifications() {
  const notifications = await api("/notifications");
  const container = document.getElementById("notificationsList");

  const unread = notifications.filter(n => !n.read_at).length;
  updateNotificationBadge(unread);

  if (!notifications.length) {
    container.innerHTML = emptyState(
      "No notifications",
      "Service updates and reminders will appear here."
    );
    return;
  }

  container.innerHTML = notifications.map(notificationCard).join("");
}

function notificationCard(notification) {
  return `
    <div class="notification-card ${
      notification.read_at ? "" : "unread"
    }">
      <div class="notification-icon">🔔</div>

      <div class="notification-content">
        <h3>${escapeHtml(notification.subject)}</h3>
        <p>${escapeHtml(notification.message)}</p>
        <small>${formatDateTime(notification.created_at)}</small>
      </div>
    </div>
  `;
}

async function markNotificationsRead() {
  try {
    // Backend marks all current user's notifications
    // as read.
    await api("/notifications/read", {
      method: "POST"
    });

    showToast("Notifications marked as read");
    await loadNotifications();
  } catch (error) {
    // Current main.py exposes GET only for notifications.
    // Reload to avoid breaking the UI if route is unavailable.
    showToast(error.message, "error");
  }
}

function updateNotificationBadge(count) {
  const badge = document.getElementById("notificationBadge");

  if (count > 0) {
    badge.textContent = count;
    badge.classList.remove("hidden");
  } else {
    badge.classList.add("hidden");
  }
}

// ============================================================
// FEEDBACK
// ============================================================

async function loadFeedback() {
  try {
    const feedback = await api("/feedback");
    const container = document.getElementById("feedbackList");

    if (!feedback.length) {
      container.innerHTML = emptyState(
        "No feedback",
        "Customer feedback will appear here."
      );
      return;
    }

    container.innerHTML = feedback
      .map(f => `
        <div class="feedback-card">
          <div class="feedback-header">
            <strong>
              ${escapeHtml(f.customer_name || "Customer")}
            </strong>

            <span>
              ${"★".repeat(f.rating)}${"☆".repeat(5 - f.rating)}
            </span>
          </div>

          <p>${escapeHtml(f.comment || "")}</p>

          <small>${formatDateTime(f.created_at)}</small>
        </div>
      `)
      .join("");
  } catch (error) {
    showToast(error.message, "error");
  }
}

// ============================================================
// POLLING
// ============================================================

function startPolling() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
  }

  pollingTimer = setInterval(async () => {
    if (!token) {
      return;
    }

    try {
      if (currentPage === "dashboard") {
        await loadDashboard();
      }

      if (currentPage === "services") {
        await loadServices();
      }

      if (currentPage === "vehicles") {
        await loadVehicles();
      }

      if (currentPage === "notifications") {
        await loadNotifications();
      }

      if (currentPage === "admin") {
        await loadAdminJobs();
      }
    } catch {
      // Silent polling failure
    }
  }, 12000);
}

// ============================================================
// MODAL
// ============================================================

function closeModal(id) {
  document.getElementById(id).classList.add("hidden");
}

document.addEventListener("click", event => {
  if (event.target.classList.contains("modal")) {
    event.target.classList.add("hidden");
  }
});

// ============================================================
// HELPERS
// ============================================================

function emptyState(title, message) {
  return `
    <div class="empty-state">
      <div class="empty-icon">📋</div>
      <h3>${escapeHtml(title)}</h3>
      <p>${escapeHtml(message)}</p>
    </div>
  `;
}

function serviceProgress(status) {
  const progressMap = {
    "Received": 10,
    "Inspection": 20,
    "Estimate Approved": 30,
    "In Service": 40,
    "Washing": 50,
    "Engine Oil Change": 60,
    "Repair / Parts": 70,
    "Quality Check": 80,
    "Ready for Pickup": 90,
    "Completed": 100
  };

  return progressMap[status] ?? 0;
}

function statusClass(status) {
  const s = String(status || "").toLowerCase();

  if (s === "completed" || s === "ready for pickup") {
    return "success";
  }

  if (s === "received" || s === "inspection") {
    return "info";
  }

  if (s === "estimate approved") {
    return "warning";
  }

  return "progress";
}

function formatDate(value) {
  if (!value) {
    return "-";
  }

  try {
    return new Date(value).toLocaleDateString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric"
    });
  } catch {
    return value;
  }
}

function formatDateTime(value) {
  if (!value) {
    return "-";
  }

  try {
    return new Date(value).toLocaleString("en-IN", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return value;
  }
}

function money(value) {
  const n = Number(value || 0);

  return n.toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function valueOrNull(value) {
  const v = String(value || "").trim();
  return v || null;
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeJs(value) {
  return String(value ?? "")
    .replaceAll("\\", "\\\\")
    .replaceAll("'", "\\'")
    .replaceAll("\n", "\\n")
    .replaceAll("\r", "\\r");
}

function showToast(message, type = "success") {
  const toast = document.getElementById("toast");

  toast.textContent = message;
  toast.className = `toast show ${type}`;

  setTimeout(() => {
    toast.className = "toast";
  }, 3500);
}

// ============================================================
// CUSTOMER SERVICE DETAILS
// ============================================================

async function openServiceDetails(jobId) {
  try {
    const jobs = await api("/jobs");

    const job = Array.isArray(jobs)
      ? jobs.find(item => Number(item.id) === Number(jobId))
      : null;

    if (!job) {
      throw new Error("Service details not found");
    }

    const existing = document.getElementById("serviceDetailsModal");

    if (existing) {
      existing.remove();
    }

    const timeline = Array.isArray(job.timeline) ? job.timeline : [];
    const progress = serviceProgress(job.status);

    const modal = document.createElement("div");
    modal.id = "serviceDetailsModal";
    modal.className = "modal service-details-modal";

    modal.innerHTML = `
      <div
        class="modal-content service-details-content"
        onclick="event.stopPropagation()"
      >
        <div class="service-details-header">
          <div>
            <span class="job-service-type">
              ${escapeHtml(job.service_type || "Service")}
            </span>

            <h2>
              ${escapeHtml(job.brand || "")}
              ${escapeHtml(job.model || "")}
            </h2>

            <p class="registration">
              ${escapeHtml(job.registration_no || "")}
            </p>
          </div>

          <button
            type="button"
            class="modal-close-btn"
            onclick="closeServiceDetails()"
          >
            ×
          </button>
        </div>

        <div class="service-detail-status">
          <span>Current Status</span>

          <strong class="status-pill ${statusClass(job.status)}">
            ${escapeHtml(job.status || "Received")}
          </strong>
        </div>

        <div class="service-detail-progress">
          <div class="progress-header">
            <span>Service Progress</span>
            <strong>${progress}%</strong>
          </div>

          <div class="progress-bar">
            <div
              class="progress-fill"
              style="width:${progress}%"
            ></div>
          </div>
        </div>

        <div class="service-detail-grid">
          <div class="detail-box">
            <span>Token</span>
            <strong>${escapeHtml(job.token_number || "-")}</strong>
          </div>

          <div class="detail-box">
            <span>Check-in</span>
            <strong>${formatDate(job.check_in_date)}</strong>
          </div>

          <div class="detail-box">
            <span>Expected Delivery</span>
            <strong>${formatDate(job.expected_delivery_date)}</strong>
          </div>

          <div class="detail-box">
            <span>Bill Amount</span>
            <strong>₹${money(job.bill_amount)}</strong>
          </div>

          <div class="detail-box">
            <span>Payment</span>
            <strong>${escapeHtml(job.payment_status || "Pending")}</strong>
          </div>

          <div class="detail-box">
            <span>Payment Method</span>
            <strong>${escapeHtml(job.payment_method || "Pending")}</strong>
          </div>

          ${
            job.odometer !== null &&
            job.odometer !== undefined
              ? `
                <div class="detail-box">
                  <span>Odometer</span>
                  <strong>${escapeHtml(job.odometer)} km</strong>
                </div>
              `
              : ""
          }

          ${
            job.assigned_executive
              ? `
                <div class="detail-box">
                  <span>Executive</span>
                  <strong>${escapeHtml(job.assigned_executive)}</strong>
                </div>
              `
              : ""
          }
        </div>

        ${
          job.complaint
            ? `
              <div class="service-detail-section">
                <h3>Customer Complaint</h3>
                <p>${escapeHtml(job.complaint)}</p>
              </div>
            `
            : ""
        }

        ${
          job.damage_details
            ? `
              <div class="service-detail-section">
                <h3>Damage Details</h3>
                <p>${escapeHtml(job.damage_details)}</p>
              </div>
            `
            : ""
        }

        ${
          job.insurance_details
            ? `
              <div class="service-detail-section">
                <h3>Insurance Details</h3>
                <p>${escapeHtml(job.insurance_details)}</p>
              </div>
            `
            : ""
        }

        ${
          job.work_done
            ? `
              <div class="service-detail-section">
                <h3>Work Completed</h3>
                <p>${escapeHtml(job.work_done)}</p>
              </div>
            `
            : ""
        }

        ${
          job.technician_notes
            ? `
              <div class="service-detail-section">
                <h3>Technician Notes</h3>
                <p>${escapeHtml(job.technician_notes)}</p>
              </div>
            `
            : ""
        }

        ${
          String(job.status || "").toLowerCase() === "completed"
            ? `
              <div
                class="service-detail-section feedback-service-section"
                id="serviceFeedbackSection-${Number(job.id)}"
              >
                <h3>Last Feedback</h3>

                <div class="service-feedback-loading muted">
                  Checking feedback...
                </div>
              </div>
            `
            : ""
        }

        <div class="service-detail-section">
          <h3>Service Timeline</h3>

          ${
            timeline.length
              ? `
                <div class="service-detail-timeline">
                  ${timeline
                    .map(item => {
                      const current =
                        String(item.stage || "").toLowerCase() ===
                        String(job.status || "").toLowerCase();

                      const completed = item.status === "Completed";

                      return `
                        <div
                          class="service-timeline-row ${
                            completed
                              ? "completed"
                              : current
                                ? "current"
                                : ""
                          }"
                        >
                          <div class="service-timeline-dot">
                            ${completed ? "✓" : ""}
                          </div>

                          <div class="service-timeline-info">
                            <strong>${escapeHtml(item.stage || "")}</strong>
                            <span>${escapeHtml(item.status || "Pending")}</span>

                            ${
                              item.notes
                                ? `<small>${escapeHtml(item.notes)}</small>`
                                : ""
                            }
                          </div>
                        </div>
                      `;
                    })
                    .join("")}
                </div>
              `
              : `
                <p class="muted">
                  Service timeline is not available yet.
                </p>
              `
          }
        </div>

        <div class="service-details-footer">
          <button
            type="button"
            class="secondary-btn"
            onclick="closeServiceDetails()"
          >
            Close
          </button>
        </div>
      </div>
    `;

    modal.addEventListener("click", event => {
      if (event.target === modal) {
        closeServiceDetails();
      }
    });

    document.body.appendChild(modal);

    requestAnimationFrame(() => {
      modal.classList.add("show");
    });

    if (String(job.status || "").toLowerCase() === "completed") {
      await loadServiceFeedback(job.id);
    }
  } catch (error) {
    showToast(
      error.message || "Unable to load service details",
      "error"
    );
  }
}

// ============================================================
// LAST FEEDBACK (inside service details)
// ============================================================

async function loadServiceFeedback(jobId) {
  const section = document.getElementById(
    `serviceFeedbackSection-${Number(jobId)}`
  );

  if (!section) {
    return;
  }

  try {
    const feedback = await api(`/feedback/my?job_id=${Number(jobId)}`);

    if (Array.isArray(feedback) && feedback.length) {
      const f = feedback[0];

      const rating = Math.max(
        0,
        Math.min(5, Number(f.rating || 0))
      );

      const stars = "★".repeat(rating) + "☆".repeat(5 - rating);

      section.innerHTML = `
        <h3>Last Feedback</h3>

        <div class="service-feedback-box">
          <div class="service-feedback-rating">
            ${stars}
          </div>

          <p>${escapeHtml(f.comment || "No comment")}</p>

          <small>
            Submitted: ${formatDateTime(f.created_at)}
          </small>
        </div>
      `;
    } else {
      section.innerHTML = `
        <h3>Last Feedback</h3>

        <p class="muted">
          You have not submitted feedback for this service yet.
        </p>

        <button
          type="button"
          class="primary-btn feedback-inline-btn"
          onclick="openFeedbackForm(${Number(jobId)})"
        >
          ★ Give Feedback
        </button>
      `;
    }
  } catch (error) {
    console.error("Feedback loading error:", error);

    section.innerHTML = `
      <h3>Last Feedback</h3>

      <p class="muted">
        Unable to load feedback right now.
      </p>
    `;
  }
}

// ============================================================
// FEEDBACK FORM
// ============================================================

function openFeedbackForm(jobId) {
  const existing = document.getElementById("feedbackFormModal");

  if (existing) {
    existing.remove();
  }

  const modal = document.createElement("div");
  modal.id = "feedbackFormModal";
  modal.className = "modal service-details-modal";

  modal.innerHTML = `
    <div
      class="modal-content feedback-form-content"
      onclick="event.stopPropagation()"
    >
      <div class="service-details-header">
        <div>
          <span class="job-service-type">Service Completed</span>
          <h2>Give Feedback</h2>
          <p class="registration">
            How was your service experience?
          </p>
        </div>

        <button
          type="button"
          class="modal-close-btn"
          onclick="closeFeedbackForm()"
        >
          ×
        </button>
      </div>

      <form
        onsubmit="submitServiceFeedback(event, ${Number(jobId)})"
      >
        <label>Your Rating</label>

        <div class="feedback-rating-input">
          ${[1, 2, 3, 4, 5]
            .map(
              number => `
                <button
                  type="button"
                  class="rating-star"
                  data-rating="${number}"
                  onclick="selectFeedbackRating(${number})"
                >
                  ☆
                </button>
              `
            )
            .join("")}
        </div>

        <input
          type="hidden"
          id="feedbackRating"
          value="0"
        />

        <label for="feedbackComment">Your message</label>

        <textarea
          id="feedbackComment"
          rows="5"
          maxlength="1000"
          placeholder="Tell us about your service experience..."
        ></textarea>

        <div class="modal-actions">
          <button
            type="button"
            class="secondary-btn"
            onclick="closeFeedbackForm()"
          >
            Cancel
          </button>

          <button
            type="submit"
            class="primary-btn"
          >
            Submit Feedback
          </button>
        </div>
      </form>
    </div>
  `;

  modal.addEventListener("click", event => {
    if (event.target === modal) {
      closeFeedbackForm();
    }
  });

  document.body.appendChild(modal);

  requestAnimationFrame(() => {
    modal.classList.add("show");
  });
}

function selectFeedbackRating(rating) {
  const ratingInput = document.getElementById("feedbackRating");

  if (!ratingInput) {
    return;
  }

  ratingInput.value = String(rating);

  document
    .querySelectorAll("#feedbackFormModal .rating-star")
    .forEach(button => {
      const value = Number(button.dataset.rating);

      button.textContent = value <= rating ? "★" : "☆";
      button.classList.toggle("selected", value <= rating);
    });
}

async function submitServiceFeedback(event, jobId) {
  event.preventDefault();

  const rating = Number(document.getElementById("feedbackRating").value);
  const comment = document.getElementById("feedbackComment").value.trim();

  if (!rating) {
    showToast("Please select a rating", "error");
    return;
  }

  try {
    await api("/feedback", {
      method: "POST",
      body: JSON.stringify({
        job_id: Number(jobId),
        rating: rating,
        comment: comment
      })
    });

    closeFeedbackForm();
    showToast("Thank you for your feedback!");
    await loadServiceFeedback(jobId);
  } catch (error) {
    showToast(
      error.message || "Unable to submit feedback",
      "error"
    );
  }
}

function closeFeedbackForm() {
  const modal = document.getElementById("feedbackFormModal");

  if (!modal) {
    return;
  }

  modal.classList.remove("show");

  setTimeout(() => modal.remove(), 200);
}

function closeServiceDetails() {
  const modal = document.getElementById("serviceDetailsModal");

  if (modal) {
    modal.classList.remove("show");

    setTimeout(() => {
      modal.remove();
    }, 200);
  }
}

// ============================================================
// GLOBAL ESC KEY
// ============================================================

document.addEventListener("keydown", event => {
  if (event.key !== "Escape") {
    return;
  }

  document.querySelectorAll(".modal").forEach(modal => {
    modal.classList.add("hidden");
  });
});