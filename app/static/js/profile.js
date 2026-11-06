/* 个人信息页：资料保存 / 密码修改，成功后同步顶栏昵称与头像字母 */
(function () {
  const formProfile = document.getElementById('formProfile');
  const formPassword = document.getElementById('formPassword');
  const deleteModal = document.getElementById('modalAccountDelete');
  const deletePassword = document.getElementById('accountDeletePassword');
  deleteModal?.querySelector('[data-close]')?.addEventListener('click', function () {
    App.closeModal('modalAccountDelete');
    deletePassword.value = '';
  });
  document.getElementById('openAccountDelete')?.addEventListener('click', function () {
    deletePassword.value = '';
    App.openModal('modalAccountDelete');
    deletePassword.focus();
  });
  deleteModal?.querySelectorAll('[data-delete-mode]').forEach(function (button) {
    button.addEventListener('click', async function () {
      if (!deletePassword.value) { App.toast('请输入当前密码', true); deletePassword.focus(); return; }
      const buttons = deleteModal.querySelectorAll('button');
      buttons.forEach(function (item) { item.disabled = true; });
      try {
        await App.api('/api/profile/account', { method: 'DELETE', body: {
          mode: button.dataset.deleteMode, current_password: deletePassword.value,
        } });
        location.href = '/login';
      } catch (err) {
        App.toast(err.message, true);
        buttons.forEach(function (item) { item.disabled = false; });
      }
    });
  });

  function syncIdentity(displayName) {
    if (!displayName) return;
    const nameEl = document.querySelector('.user-chip .user-chip-name');
    if (nameEl) nameEl.textContent = displayName;
    const avatar = document.querySelector('.user-chip .user-avatar');
    if (avatar) avatar.textContent = displayName[0];
    // 左侧账号概览同步昵称与头像首字，避免保存后概览仍显示旧名
    const sideName = document.getElementById('profileName');
    if (sideName) sideName.textContent = displayName;
    const sideAvatar = document.getElementById('profileAvatar');
    if (sideAvatar) sideAvatar.textContent = displayName[0];
  }

  if (formProfile) {
    formProfile.addEventListener('submit', async function (e) {
      e.preventDefault();
      const body = {
        display_name: formProfile.display_name.value.trim(),
        gender: formProfile.gender.value,
        age: formProfile.age.value,
      };
      try {
        const data = await App.api('/api/profile', { method: 'POST', body });
        syncIdentity(data.display_name);
        App.toast('资料已保存');
      } catch (err) {
        App.toast(err.message, true);
      }
    });
  }

  if (formPassword) {
    formPassword.addEventListener('submit', async function (e) {
      e.preventDefault();
      if (formPassword.new_password.value !== formPassword.confirm_password.value) {
        App.toast('两次输入的新密码不一致', true);
        return;
      }
      const body = {
        current_password: formPassword.current_password.value,
        new_password: formPassword.new_password.value,
        confirm_password: formPassword.confirm_password.value,
      };
      try {
        await App.api('/api/profile/password', { method: 'POST', body });
        App.toast('密码已更新');
        formPassword.reset();
      } catch (err) {
        App.toast(err.message, true);
      }
    });
  }
})();
