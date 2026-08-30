/**
 * revisionPlan.js — Revision plan rendering for StudyLens AI
 *
 * Exports:
 *   renderRevisionPlan(plan) — populates the revision plan section of
 *   #report-panel with an ordered list of revision tasks and a total
 *   time summary.
 *
 * Security: all AI-generated text (task titles, descriptions) is set
 * via textContent — never innerHTML — to prevent XSS.
 */

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format a duration in minutes into a human-readable string.
 * @param {number} minutes
 * @returns {string} e.g. "1 hr 30 min", "45 min", "2 hr"
 */
function _formatDuration(minutes) {
  if (!minutes || minutes <= 0) return '0 min';
  const hrs  = Math.floor(minutes / 60);
  const mins = minutes % 60;
  if (hrs > 0 && mins > 0) return `${hrs} hr ${mins} min`;
  if (hrs > 0)              return `${hrs} hr`;
  return `${mins} min`;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Render a revision plan into the existing #revision-plan-container section.
 *
 * Expected shape of `plan`:
 * {
 *   tasks: [
 *     {
 *       title:            string,
 *       description:      string,
 *       duration_minutes: number,
 *       gap_ref:          string | null,
 *       is_maintenance:   boolean
 *     }
 *   ],
 *   total_minutes: number
 * }
 *
 * @param {object|null|undefined} plan - Revision plan from the API response.
 */
export function renderRevisionPlan(plan) {
  const tasksList   = document.getElementById('revision-tasks-list');
  const totalTime   = document.getElementById('revision-total-time');

  // Clear previous content
  if (tasksList) tasksList.textContent = '';
  if (totalTime) totalTime.textContent = '';

  // Gracefully handle null/undefined/missing plan
  if (!plan) {
    if (totalTime) totalTime.textContent = 'No revision plan available.';
    return;
  }

  const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];

  // Handle empty task list
  if (tasks.length === 0) {
    if (totalTime) totalTime.textContent = 'No revision tasks generated.';
    return;
  }

  // Render total time summary
  if (totalTime) {
    const total = typeof plan.total_minutes === 'number' ? plan.total_minutes : 0;
    totalTime.textContent = `Total estimated revision time: ${_formatDuration(total)}`;
  }

  // Render each task as an <li> inside the <ol>
  if (!tasksList) return;

  tasks.forEach((task, index) => {
    const li = document.createElement('li');
    li.className = task.is_maintenance ? 'revision-task revision-task--maintenance' : 'revision-task';

    // Task header: title + duration badge
    const header = document.createElement('div');
    header.className = 'revision-task-header';

    const titleEl = document.createElement('span');
    titleEl.className = 'revision-task-title';
    titleEl.textContent = task.title ?? `Task ${index + 1}`;  // textContent — AI text

    const durationEl = document.createElement('span');
    durationEl.className = 'revision-task-duration';
    const mins = typeof task.duration_minutes === 'number' ? task.duration_minutes : 0;
    durationEl.textContent = _formatDuration(mins);

    header.appendChild(titleEl);
    header.appendChild(durationEl);
    li.appendChild(header);

    // Task description
    if (task.description) {
      const descEl = document.createElement('p');
      descEl.className = 'revision-task-description';
      descEl.textContent = task.description;  // textContent — AI-generated text
      li.appendChild(descEl);
    }

    tasksList.appendChild(li);
  });
}
