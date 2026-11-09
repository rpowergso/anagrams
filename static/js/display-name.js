const displayNameKey = 'anagramsMultiplayerUsername';

function cleanDisplayName(value) {
    const name = value.trim().replace(/\s+/gu, ' ');
    return name.length <= 24 && /^[\p{L}\p{N} _.'-]+$/u.test(name) ? name : '';
}

function getDisplayName() {
    return cleanDisplayName(localStorage.getItem(displayNameKey) ||
        sessionStorage.getItem(displayNameKey) || '');
}

function saveDisplayName(name) {
    localStorage.setItem(displayNameKey, name);
    sessionStorage.setItem(displayNameKey, name);
}

function setupDisplayNameForm(updateName = async name => name) {
    const form = document.getElementById('display-name-form');
    const input = form.elements.displayName;
    const button = form.querySelector('button');
    const status = form.querySelector('[role="status"]');
    input.value = getDisplayName();
    input.addEventListener('input', () => { status.textContent = ''; });
    form.addEventListener('submit', async event => {
        event.preventDefault();
        const name = cleanDisplayName(input.value);
        if (!name) {
            status.textContent = "Use 1–24 characters: letters, numbers, spaces, apostrophes, periods, hyphens, or underscores.";
            return;
        }
        button.disabled = true;
        input.readOnly = true;
        try {
            const savedName = await updateName(name);
            saveDisplayName(savedName);
            input.value = savedName;
            status.textContent = 'Display name saved.';
            form.dispatchEvent(new Event('display-name-saved'));
        } catch (error) {
            status.textContent = error.message;
        } finally {
            button.disabled = false;
            input.readOnly = false;
        }
    });
}
