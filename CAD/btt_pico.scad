$fn=100;

bh=58;
m25=2.7/2;
z=3;
buffer=20;
m5=2.6;
w=40;

difference(){
    cube([w,bh+buffer,z],center=true);
    translate([w/2-10,0,-10])
    cylinder(100,m5,m5);
    translate([-(w/2-10),bh/2,-10])
    cylinder(100,m25,m25);
    translate([-(w/2-10),-bh/2,-10])
    cylinder(100,m25,m25);
    
}