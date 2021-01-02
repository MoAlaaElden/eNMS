var CSS2DObject = function (e) {
  THREE.Object3D.call(this),
    (this.element = e || document.createElement("div")),
    (this.element.style.position = "absolute"),
    this.addEventListener("removed", function () {
      this.traverse(function (e) {
        e.element instanceof Element &&
          null !== e.element.parentNode &&
          e.element.parentNode.removeChild(e.element);
      });
    });
};
CSS2DObject.prototype = Object.assign(Object.create(THREE.Object3D.prototype), {
  constructor: CSS2DObject,
  copy: function (e, t) {
    return (
      THREE.Object3D.prototype.copy.call(this, e, t),
      (this.element = e.element.cloneNode(!0)),
      this
    );
  },
});
var CSS2DRenderer = function () {
  var e,
    t,
    n,
    r,
    o = this,
    i = new THREE.Vector3(),
    a = new THREE.Matrix4(),
    s = new THREE.Matrix4(),
    c = { objects: new WeakMap() },
    l = document.createElement("div");
  (l.style.overflow = "hidden"),
    (this.domElement = l),
    (this.getSize = function () {
      return { width: e, height: t };
    }),
    (this.setSize = function (o, i) {
      (n = (e = o) / 2),
        (r = (t = i) / 2),
        (l.style.width = o + "px"),
        (l.style.height = i + "px");
    });
  var d,
    m,
    u = function (e, t, a) {
      if (e instanceof CSS2DObject) {
        e.onBeforeRender(o, t, a),
          i.setFromMatrixPosition(e.matrixWorld),
          i.applyMatrix4(s);
        var d = e.element,
          m =
            "translate(-50%,-50%) translate(" +
            (i.x * n + n) +
            "px," +
            (-i.y * r + r) +
            "px)";
        (d.style.WebkitTransform = m),
          (d.style.MozTransform = m),
          (d.style.oTransform = m),
          (d.style.transform = m),
          (d.style.display = e.visible && i.z >= -1 && i.z <= 1 ? "" : "none");
        var h = { distanceToCameraSquared: p(a, e) };
        c.objects.set(e, h),
          d.parentNode !== l && l.appendChild(d),
          e.onAfterRender(o, t, a);
      }
      for (var f = 0, E = e.children.length; f < E; f++) u(e.children[f], t, a);
    },
    p =
      ((d = new THREE.Vector3()),
      (m = new THREE.Vector3()),
      function (e, t) {
        return (
          d.setFromMatrixPosition(e.matrixWorld),
          m.setFromMatrixPosition(t.matrixWorld),
          d.distanceToSquared(m)
        );
      }),
    h = function (e) {
      for (
        var t = (function (e) {
            var t = [];
            return (
              e.traverse(function (e) {
                e instanceof CSS2DObject && t.push(e);
              }),
              t
            );
          })(e).sort(function (e, t) {
            return (
              c.objects.get(e).distanceToCameraSquared -
              c.objects.get(t).distanceToCameraSquared
            );
          }),
          n = t.length,
          r = 0,
          o = t.length;
        r < o;
        r++
      )
        t[r].element.style.zIndex = n - r;
    };
  this.render = function (e, t) {
    !0 === e.autoUpdate && e.updateMatrixWorld(),
      null === t.parent && t.updateMatrixWorld(),
      a.copy(t.matrixWorldInverse),
      s.multiplyMatrices(t.projectionMatrix, a),
      u(e, e, t),
      h(e);
  };
};
