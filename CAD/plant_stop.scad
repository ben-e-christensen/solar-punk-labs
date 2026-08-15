$fn=100;

in=25.4;
r=(in-.4)/2;
ID=10;
r2=ID/2;
difference(){
    
    cylinder(1/4*in,r,r);
    translate([0,0,-1/4*in])
    cylinder(100,r2,r2);
}
translate([0,0,1/4*in])
difference(){
    cylinder(2,r+5,r+5);
    translate([0,0,-1/4*in])
    cylinder(100,r2,r2);
}