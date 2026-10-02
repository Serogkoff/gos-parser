(() => {
    const mobileViewport = window.matchMedia('(max-width:920px)');
    let animationFrame = 0;

    function updateMobileBottomNav(){
        animationFrame = 0;
        const navigationBars = document.querySelectorAll('.mobile-bottom-nav');
        if(!navigationBars.length) return;

        if(!mobileViewport.matches){
            navigationBars.forEach(navigation => {
                navigation.style.removeProperty('top');
                navigation.style.removeProperty('bottom');
            });
            return;
        }

        const viewport = window.visualViewport;
        const visibleBottom = viewport
            ? viewport.offsetTop + viewport.height
            : window.innerHeight;

        navigationBars.forEach(navigation => {
            if(window.getComputedStyle(navigation).display === 'none') return;
            const navigationHeight = navigation.getBoundingClientRect().height;
            if(!navigationHeight) return;
            const navigationTop = Math.max(0, Math.round(visibleBottom - navigationHeight));
            navigation.style.setProperty('top', `${navigationTop}px`, 'important');
            navigation.style.setProperty('bottom', 'auto', 'important');
        });
    }

    function scheduleMobileBottomNavUpdate(){
        if(animationFrame) window.cancelAnimationFrame(animationFrame);
        animationFrame = window.requestAnimationFrame(updateMobileBottomNav);
    }

    window.syncMobileBottomNav = scheduleMobileBottomNavUpdate;
    window.addEventListener('resize', scheduleMobileBottomNavUpdate, {passive:true});
    window.addEventListener('orientationchange', scheduleMobileBottomNavUpdate, {passive:true});
    window.addEventListener('pageshow', scheduleMobileBottomNavUpdate, {passive:true});
    mobileViewport.addEventListener?.('change', scheduleMobileBottomNavUpdate);
    window.visualViewport?.addEventListener('resize', scheduleMobileBottomNavUpdate, {passive:true});
    window.visualViewport?.addEventListener('scroll', scheduleMobileBottomNavUpdate, {passive:true});
    scheduleMobileBottomNavUpdate();
})();
