$fn=100;

nema_w=42.3;
nema_h=39.5;
bhd=31;
m3=1.6;
m5=2.6;
shaft_d=26;
z=3;


module latch(){
    difference(){
        cube([20,40,z],center=true);
        for(i=[0:1]){
            translate([0,10 -20*i,-z])
            cylinder(10,m5,m5);
        }
    }
}

module nema(){
    cube([nema_w,nema_w,nema_h+.1],center=true);
    for(i=[0:3]){
        rotate([0,0,90*i])
        translate([bhd/2,bhd/2,0])
        cylinder(nema_h+10,m3,m3);
    }
    cylinder(nema_h+10,d=shaft_d);

}

module bracket() {
    difference(){
        translate([0,0,z])
        cube([nema_w-.1,nema_w+z*2,nema_h+z*2],center=true);
        //cube([10,100,nema_h],center=true);
        nema();
    }
    for(i=[0:1]){
        rotate([0,0,90])
        translate([(-1)^i*(nema_w/2+10+z),0,-nema_h/2+z/2])
        latch();
    }
}
model=false;
if(model){
color("blue")
nema();
}
bracket();