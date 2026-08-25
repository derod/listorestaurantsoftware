/**
 * MODERN MODAL SYSTEM
 * Replaces browser alert(), confirm(), prompt() with beautiful custom modals
 */

const ModernModal = {
    /**
     * Show alert modal
     * @param {string} message - The message to display
     * @param {string} type - 'success', 'error', 'warning', 'info'
     * @param {string} title - Optional title
     */
    alert: function(message, type = 'info', title = '') {
        return new Promise((resolve) => {
            const icons = {
                success: '✅',
                error: '❌',
                warning: '⚠️',
                info: 'ℹ️'
            };
            
            const titles = {
                success: title || 'Éxito',
                error: title || 'Error',
                warning: title || 'Advertencia',
                info: title || 'Información'
            };
            
            const modal = this.createModal({
                icon: icons[type],
                title: titles[type],
                message: message,
                type: type,
                buttons: [
                    { text: 'Entendido', class: 'modal-btn-primary', action: 'close' }
                ]
            });
            
            modal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal-btn') || 
                    e.target.classList.contains('modal-overlay')) {
                    this.closeModal(modal);
                    resolve(true);
                }
            });
        });
    },

    /**
     * Show confirm modal
     * @param {string} message - The confirmation message
     * @param {string} title - Optional title
     */
    confirm: function(message, title = '¿Estás seguro?') {
        return new Promise((resolve) => {
            const modal = this.createModal({
                icon: '❓',
                title: title,
                message: message,
                type: 'question',
                buttons: [
                    { text: 'Cancelar', class: 'modal-btn-secondary', action: 'cancel' },
                    { text: 'Confirmar', class: 'modal-btn-primary', action: 'confirm' }
                ]
            });
            
            modal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal-btn')) {
                    const action = e.target.dataset.action;
                    this.closeModal(modal);
                    resolve(action === 'confirm');
                } else if (e.target.classList.contains('modal-overlay')) {
                    this.closeModal(modal);
                    resolve(false);
                }
            });
        });
    },

    /**
     * Show prompt modal
     * @param {string} message - The prompt message
     * @param {string} placeholder - Input placeholder
     * @param {string} defaultValue - Default input value
     */
    prompt: function(message, placeholder = '', defaultValue = '') {
        return new Promise((resolve) => {
            const modal = this.createModal({
                icon: '✏️',
                title: 'Ingresa un valor',
                message: message,
                type: 'info',
                input: {
                    type: 'text',
                    placeholder: placeholder,
                    value: defaultValue
                },
                buttons: [
                    { text: 'Cancelar', class: 'modal-btn-secondary', action: 'cancel' },
                    { text: 'Aceptar', class: 'modal-btn-primary', action: 'accept' }
                ]
            });
            
            const input = modal.querySelector('.modal-input');
            if (input) {
                input.focus();
                input.select();
            }
            
            modal.addEventListener('click', (e) => {
                if (e.target.classList.contains('modal-btn')) {
                    const action = e.target.dataset.action;
                    const value = input ? input.value : null;
                    this.closeModal(modal);
                    resolve(action === 'accept' ? value : null);
                } else if (e.target.classList.contains('modal-overlay')) {
                    this.closeModal(modal);
                    resolve(null);
                }
            });
            
            // Allow Enter key to submit
            if (input) {
                input.addEventListener('keypress', (e) => {
                    if (e.key === 'Enter') {
                        this.closeModal(modal);
                        resolve(input.value);
                    }
                });
            }
        });
    },

    /**
     * Show loading modal
     * @param {string} message - Loading message
     */
    loading: function(message = 'Cargando...') {
        const modal = this.createModal({
            icon: '<div class="modal-loading"></div>',
            title: message,
            message: 'Por favor espera',
            type: 'info',
            buttons: []
        });
        
        return {
            close: () => this.closeModal(modal)
        };
    },

    /**
     * Create modal element
     * @private
     */
    createModal: function(config) {
        const overlay = document.createElement('div');
        overlay.className = 'modal-overlay active';
        
        const box = document.createElement('div');
        box.className = `modal-box ${config.type}`;
        
        const header = document.createElement('div');
        header.className = 'modal-header';
        
        if (config.icon) {
            const icon = document.createElement('div');
            icon.className = 'modal-icon';
            if (config.icon.startsWith('<')) {
                icon.innerHTML = config.icon;
            } else {
                icon.textContent = config.icon;
            }
            header.appendChild(icon);
        }
        
        if (config.title) {
            const title = document.createElement('h3');
            title.className = 'modal-title';
            title.textContent = config.title;
            header.appendChild(title);
        }
        
        if (config.message) {
            const message = document.createElement('p');
            message.className = 'modal-message';
            message.textContent = config.message;
            header.appendChild(message);
        }
        
        box.appendChild(header);
        
        // Add input if needed
        if (config.input) {
            const input = document.createElement('input');
            input.className = 'modal-input';
            input.type = config.input.type || 'text';
            input.placeholder = config.input.placeholder || '';
            input.value = config.input.value || '';
            box.appendChild(input);
        }
        
        // Add buttons
        if (config.buttons && config.buttons.length > 0) {
            const buttonsContainer = document.createElement('div');
            buttonsContainer.className = 'modal-buttons';
            
            config.buttons.forEach(btn => {
                const button = document.createElement('button');
                button.className = `modal-btn ${btn.class}`;
                button.textContent = btn.text;
                button.dataset.action = btn.action;
                buttonsContainer.appendChild(button);
            });
            
            box.appendChild(buttonsContainer);
        }
        
        overlay.appendChild(box);
        document.body.appendChild(overlay);
        
        // Prevent body scroll
        document.body.style.overflow = 'hidden';
        
        return overlay;
    },

    /**
     * Close modal
     * @private
     */
    closeModal: function(modal) {
        modal.classList.remove('active');
        setTimeout(() => {
            if (modal.parentNode) {
                modal.parentNode.removeChild(modal);
            }
            // Re-enable body scroll if no other modals
            if (!document.querySelector('.modal-overlay.active')) {
                document.body.style.overflow = '';
            }
        }, 200);
    }
};

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ModernModal;
}
